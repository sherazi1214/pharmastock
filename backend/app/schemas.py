import re
from typing import Literal

from pydantic import BaseModel, Field, field_validator

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.-]{3,30}$")
Role = Literal["owner", "salesperson", "stock_operator"]


def strip_str(v):
    return v.strip() if isinstance(v, str) else v


def check_username(v: str) -> str:
    if not USERNAME_RE.match(v):
        raise ValueError("must be 3 to 30 letters, numbers, dot, dash or underscore (no spaces)")
    return v


def check_password(v: str) -> str:
    if len(v) < 8:
        raise ValueError("must be at least 8 characters")
    if len(v.encode("utf-8")) > 72:
        raise ValueError("is too long (maximum 72 characters)")
    return v


class SetupIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=100)
    owner_name: str = Field(min_length=2, max_length=100)
    username: str
    password: str
    _s = field_validator("business_name", "owner_name", "username", mode="before")(strip_str)
    _u = field_validator("username")(check_username)
    _p = field_validator("password")(check_password)


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=200)
    _s = field_validator("username", mode="before")(strip_str)


class SettingsIn(BaseModel):
    business_name: str = Field(min_length=2, max_length=100)
    owner_name: str = Field(min_length=2, max_length=100)
    address: str = Field(default="", max_length=300)
    phone: str = Field(default="", max_length=40)
    licence_number: str = Field(default="", max_length=60)
    payment_methods: list[str]
    near_expiry_days: int = Field(ge=1, le=3650)
    _s = field_validator("business_name", "owner_name", "address", "phone", "licence_number", mode="before")(strip_str)

    @field_validator("payment_methods")
    @classmethod
    def clean_methods(cls, v: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for item in v:
            name = item.strip()
            if not name:
                continue
            if len(name) > 30:
                raise ValueError("each payment method must be 30 characters or less")
            if name.lower() not in seen:
                seen.add(name.lower())
                cleaned.append(name)
        if not cleaned:
            raise ValueError("add at least one payment method")
        if len(cleaned) > 20:
            raise ValueError("too many payment methods (maximum 20)")
        return cleaned


class UserCreateIn(BaseModel):
    username: str
    full_name: str = Field(min_length=2, max_length=100)
    password: str
    role: Role
    _s = field_validator("username", "full_name", mode="before")(strip_str)
    _u = field_validator("username")(check_username)
    _p = field_validator("password")(check_password)


class UserUpdateIn(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=100)
    role: Role | None = None
    is_active: bool | None = None
    _s = field_validator("full_name", mode="before")(strip_str)


class ResetPasswordIn(BaseModel):
    new_password: str
    _p = field_validator("new_password")(check_password)


class PermissionsIn(BaseModel):
    permissions: list[str]
