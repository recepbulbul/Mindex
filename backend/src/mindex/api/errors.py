"""Exception handlers that keep every error in the `{detail, fields?}` envelope.

FastAPI's default 422 body is `{"detail": [{loc, msg, ...}]}`; the frontend expects a message
plus a field → message map it can show next to form inputs.
"""

from collections.abc import Sequence
from typing import Any, cast

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mindex.api.schemas import ApiErrorBody

VALIDATION_DETAIL = "Gönderilen veriler geçersiz."


def _field_name(loc: Sequence[Any]) -> str:
    # ("body", "startDate") -> "startDate"; ("query", "limit") -> "limit"
    parts = [str(p) for p in loc[1:]] if len(loc) > 1 else [str(p) for p in loc]
    return ".".join(parts) or "body"


def validation_fields(errors: Sequence[Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for err in errors:
        e = cast(dict[str, Any], err)
        name = _field_name(cast(Sequence[Any], e.get("loc", ())))
        fields.setdefault(name, str(e.get("msg", "geçersiz")))
    return fields


def _json(status: int, body: ApiErrorBody, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(
        body.model_dump(by_alias=True, exclude_none=True), status_code=status, headers=headers
    )


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    e = cast(StarletteHTTPException, exc)
    return _json(
        e.status_code, ApiErrorBody(detail=e.detail), cast(dict[str, str] | None, e.headers)
    )


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    e = cast(RequestValidationError, exc)
    return _json(422, ApiErrorBody(detail=VALIDATION_DETAIL, fields=validation_fields(e.errors())))


def install(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
