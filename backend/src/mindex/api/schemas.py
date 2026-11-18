"""Base for API schemas: camelCase on the wire (frontend/src/api/types.ts), snake_case in Python."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, EmailStr, Field
from pydantic.alias_generators import to_camel

from mindex.db.models import UserRole


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
        extra="forbid",
    )


class ApiErrorBody(ApiModel):
    """Every error response: `{detail, fields?}` (frontend `ApiErrorBody`)."""

    detail: str
    fields: dict[str, str] | None = None


class Health(ApiModel):
    status: Literal["ok", "degraded"]
    database: bool


# ---------------------------------------------------------------- auth (F1)

Email = Annotated[EmailStr, AfterValidator(lambda e: e.lower())]
# Upper bound keeps one request from making Argon2 hash megabytes (cheap DoS).
Password = Annotated[str, Field(min_length=8, max_length=128)]


class LoginRequest(ApiModel):
    email: Email
    password: str = Field(min_length=1, max_length=128)


class RegisterRequest(ApiModel):
    email: Email
    password: Password


class UserOut(ApiModel):
    email: str
    role: UserRole


class LoginResponse(ApiModel):
    token: str
    user: UserOut
