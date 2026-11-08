from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .db import init_db
from .routes_admin import router as admin_router
from .routes_auth import router as auth_router
from .routes_products import router as products_router
from .routes_phase3 import router as phase3_router
from .routes_phase4 import router as phase4_router
from .routes_phase5 import router as phase5_router
from .routes_phase6 import router as phase6_router
from .security import install_security, mount_frontend


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="PharmaStock 2027 API", version="1.0.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(products_router)
app.include_router(phase3_router)
app.include_router(phase4_router)
app.include_router(phase5_router)
app.include_router(phase6_router)
install_security(app)


@app.exception_handler(RequestValidationError)
async def friendly_validation_errors(request: Request, exc: RequestValidationError):
    parts = []
    for err in exc.errors():
        where = [str(x) for x in err["loc"] if x not in ("body", "query", "path")]
        field = " ".join(where).replace("_", " ").capitalize()
        message = err["msg"].removeprefix("Value error, ")
        parts.append(f"{field} {message}" if field else message)
    return JSONResponse(status_code=422, content={"detail": ". ".join(parts)})


@app.get("/api/health")
def health():
    return {"status": "ok"}


# Must stay LAST: serves the built frontend (frontend/out) so only one program runs.
mount_frontend(app)
