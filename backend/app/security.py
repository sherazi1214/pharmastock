"""PharmaStock 2027 - Phase 7: security layer.

- login rate limit (per computer address)
- request size limits (small for normal requests, bigger for file imports)
- safe response headers
- serve the built frontend (static files) from the same program
- endpoint audit: lists API endpoints that do NOT require a login
"""
import hashlib
import os
import secrets
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

LOGIN_MAX = int(os.environ.get("PHARMASTOCK_LOGIN_MAX", "10"))       # tries
LOGIN_WINDOW = int(os.environ.get("PHARMASTOCK_LOGIN_WINDOW", "60"))  # seconds
MAX_JSON_BYTES = int(os.environ.get("PHARMASTOCK_MAX_JSON_MB", "2")) * 1024 * 1024
MAX_UPLOAD_BYTES = int(os.environ.get("PHARMASTOCK_MAX_UPLOAD_MB", "25")) * 1024 * 1024
UPLOAD_WORDS = ("import", "upload")


class _TooBig(Exception):
    pass


class BodyLimitMiddleware:
    """Refuses requests whose body is bigger than the limit (checked by header AND while reading)."""

    def __init__(self, app, json_bytes: int = MAX_JSON_BYTES, upload_bytes: int = MAX_UPLOAD_BYTES):
        self.app, self.json_bytes, self.upload_bytes = app, json_bytes, upload_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        path = scope["path"].lower()
        limit = self.upload_bytes if any(w in path for w in UPLOAD_WORDS) else self.json_bytes
        headers = dict(scope["headers"])
        started = False

        async def deny():
            body = b'{"detail":"The file or request is too big."}'
            await send({"type": "http.response.start", "status": 413,
                        "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})

        cl = headers.get(b"content-length")
        if cl and cl.isdigit() and int(cl) > limit:
            return await deny()
        total = 0

        async def counting_receive():
            nonlocal total
            msg = await receive()
            if msg["type"] == "http.request":
                total += len(msg.get("body", b""))
                if total > limit:
                    raise _TooBig()
            return msg

        async def tracking_send(msg):
            nonlocal started
            if msg["type"] == "http.response.start":
                started = True
            await send(msg)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _TooBig:
            if not started:
                await deny()


class LoginRateLimitMiddleware:
    """At most LOGIN_MAX login tries per LOGIN_WINDOW seconds from one computer address."""

    def __init__(self, app, max_tries: int = LOGIN_MAX, window: int = LOGIN_WINDOW):
        self.app, self.max_tries, self.window = app, max_tries, window
        self.hits: dict[str, deque] = defaultdict(deque)

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and scope["method"] == "POST" and scope["path"].rstrip("/").lower().endswith("/login"):
            ip = (scope.get("client") or ("unknown", 0))[0]
            now = time.monotonic()
            q = self.hits[ip]
            while q and now - q[0] > self.window:
                q.popleft()
            if len(q) >= self.max_tries:
                wait = max(1, int(self.window - (now - q[0])))
                resp = JSONResponse({"detail": f"Too many login tries. Please wait {wait} seconds and try again."},
                                    status_code=429, headers={"Retry-After": str(wait)})
                return await resp(scope, receive, send)
            q.append(now)
            if len(self.hits) > 5000:  # keep memory small
                for k in [k for k, v in self.hits.items() if not v or now - v[-1] > self.window]:
                    self.hits.pop(k, None)
        return await self.app(scope, receive, send)


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        api = scope["path"].startswith("/api")

        async def wrapped(msg):
            if msg["type"] == "http.response.start":
                h = list(msg.get("headers", []))
                h += [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"), (b"referrer-policy", b"no-referrer")]
                if api:
                    h.append((b"cache-control", b"no-store"))
                msg["headers"] = h
            await send(msg)

        await self.app(scope, receive, wrapped)


class SPAStaticFiles(StaticFiles):
    """Serves the exported Next.js site. /sales -> sales/index.html or sales.html; unknown pages -> index.html."""

    async def get_response(self, path, scope):
        try:
            return await super().get_response(path, scope)
        except StarletteHTTPException as e:
            if e.status_code != 404:
                raise
            for alt in (path.rstrip("/") + ".html", "index.html"):
                try:
                    return await super().get_response(alt, scope)
                except StarletteHTTPException:
                    continue
            raise


def frontend_dir() -> Path:
    env = os.environ.get("PHARMASTOCK_FRONTEND_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "frontend" / "out"


def install_security(app: FastAPI) -> None:
    app.add_middleware(BodyLimitMiddleware)
    app.add_middleware(LoginRateLimitMiddleware)
    app.add_middleware(SecurityHeadersMiddleware)


def mount_frontend(app: FastAPI, directory: Path | None = None) -> bool:
    """Call LAST (after all API routes). Returns True if the built frontend was found."""
    d = directory or frontend_dir()
    if d.is_dir() and (d / "index.html").exists():
        app.mount("/", SPAStaticFiles(directory=str(d), html=True), name="frontend")
        return True
    return False


# ------------------------------------------------------------------ audit
PUBLIC_OK = ("/api/health", "/login", "/setup", "/docs", "/openapi.json", "/redoc", "/api/auth/status", "/api/setup")


def _dep_names(dependant, seen=None):
    seen = seen if seen is not None else set()
    for d in dependant.dependencies:
        call = d.call
        if call is not None:
            seen.add((getattr(call, "__module__", "") or "").split(".")[-1] + "." + getattr(call, "__name__", ""))
        _dep_names(d, seen)
    return seen


def endpoints_without_login(app: FastAPI, auth_modules=("deps",)) -> list[str]:
    """Every /api endpoint must depend (directly or indirectly) on something from deps.py (login / permission check)."""
    bad = []
    for r in app.routes:
        dep = getattr(r, "dependant", None)
        if dep is None or not r.path.startswith("/api"):
            continue
        if any(r.path.lower().rstrip("/").endswith(p) or r.path.lower().startswith(p) for p in PUBLIC_OK):
            continue
        if not any(n.split(".")[0] in auth_modules for n in _dep_names(dep)):
            bad.append(f"{','.join(sorted(r.methods or []))} {r.path}")
    return sorted(bad)


# ------------------------------------------------------------------ passwords and login tokens (from Phase 3)
def hash_password(password: str) -> str:
    import bcrypt
    from .config import bcrypt_rounds
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=bcrypt_rounds())).decode("ascii")


def verify_password(password: str, password_hash: str) -> bool:
    import bcrypt
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except ValueError:
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    """Only the hash of a login token is stored, so a copied database cannot be used to log in."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


_dummy = None


def dummy_hash() -> str:
    """Used so that unknown usernames take the same time as known ones."""
    global _dummy
    if _dummy is None:
        _dummy = hash_password("not-a-real-password")
    return _dummy
