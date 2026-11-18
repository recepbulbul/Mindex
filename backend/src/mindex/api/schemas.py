"""Base for API schemas: camelCase on the wire (frontend/src/api/types.ts), snake_case in Python."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


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
    status: str
    database: bool
