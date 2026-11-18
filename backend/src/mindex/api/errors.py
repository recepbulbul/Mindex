"""Exception handlers that keep every error in the `{detail, fields?}` envelope, in Turkish.

FastAPI's default 422 body is `{"detail": [{loc, msg, ...}]}` and an unhandled exception is a
plain-text 500; the frontend expects a message plus a field → message map it can show next
to form inputs, always as JSON.
"""

from collections.abc import Mapping, Sequence
from http import HTTPStatus
from typing import Any, cast

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from mindex.api.schemas import ApiErrorBody

VALIDATION_DETAIL = "Gönderilen veriler geçersiz."
INTERNAL_DETAIL = "Beklenmeyen bir sunucu hatası oluştu."
GENERIC_DETAIL = "İstek işlenemedi."

# Messages for the statuses Starlette raises itself (its own details are English).
STATUS_DETAILS: Mapping[int, str] = {
    400: "İstek geçersiz.",
    401: "Oturum gerekli.",
    403: "Bu işlem için yetkiniz yok.",
    404: "Kaynak bulunamadı.",
    405: "Bu yöntem desteklenmiyor.",
    409: "İstek mevcut durumla çakışıyor.",
    413: "İstek çok büyük.",
    415: "Desteklenmeyen içerik türü.",
    429: "Çok fazla istek. Biraz sonra tekrar deneyin.",
    500: INTERNAL_DETAIL,
}

# Pydantic error types → field messages; anything else falls back to a generic one.
FIELD_MESSAGES: Mapping[str, str] = {
    "missing": "Zorunlu alan.",
    "extra_forbidden": "Bilinmeyen alan.",
    "int_parsing": "Tam sayı olmalı.",
    "int_type": "Tam sayı olmalı.",
    "float_parsing": "Sayı olmalı.",
    "float_type": "Sayı olmalı.",
    "bool_parsing": "Doğru/yanlış olmalı.",
    "string_type": "Metin olmalı.",
    "string_too_short": "Çok kısa.",
    "string_too_long": "Çok uzun.",
    "date_parsing": "Geçerli bir tarih olmalı (YYYY-AA-GG).",
    "date_from_datetime_parsing": "Geçerli bir tarih olmalı (YYYY-AA-GG).",
    "date_type": "Geçerli bir tarih olmalı (YYYY-AA-GG).",
    "enum": "İzin verilen değerlerden biri olmalı.",
    "literal_error": "İzin verilen değerlerden biri olmalı.",
    "greater_than": "Daha büyük olmalı.",
    "greater_than_equal": "Daha büyük olmalı.",
    "less_than": "Daha küçük olmalı.",
    "less_than_equal": "Daha küçük olmalı.",
    "too_short": "Çok az öğe.",
    "too_long": "Çok fazla öğe.",
    "json_invalid": "Geçerli JSON olmalı.",
}
DEFAULT_FIELD_MESSAGE = "Geçersiz değer."

log = structlog.get_logger(__name__)


def _field_name(loc: Sequence[Any]) -> str:
    # ("body", "startDate") -> "startDate"; ("query", "limit") -> "limit"
    parts = [str(p) for p in loc[1:]] if len(loc) > 1 else [str(p) for p in loc]
    return ".".join(parts) or "body"


def _field_message(err: Mapping[str, Any]) -> str:
    # Our own validators raise ValueError with a Turkish message; Pydantic keeps it in ctx.
    if err.get("type") == "value_error":
        ctx = cast(Mapping[str, Any], err.get("ctx") or {})
        if "error" in ctx:
            return str(ctx["error"])
    return FIELD_MESSAGES.get(str(err.get("type", "")), DEFAULT_FIELD_MESSAGE)


def validation_fields(errors: Sequence[Any]) -> dict[str, str]:
    fields: dict[str, str] = {}
    for err in errors:
        e = cast(Mapping[str, Any], err)
        name = _field_name(cast(Sequence[Any], e.get("loc", ())))
        fields.setdefault(name, _field_message(e))
    return fields


def _status_detail(status: int) -> str:
    return STATUS_DETAILS.get(status, GENERIC_DETAIL)


def _reason_phrase(status: int) -> str:
    try:
        return HTTPStatus(status).phrase
    except ValueError:
        return ""


def error_body(exc: StarletteHTTPException) -> ApiErrorBody:
    """`detail` may be our Turkish message, a `{detail, fields}` dict, or Starlette's default
    English reason phrase, which is replaced by the Turkish message for that status."""
    detail = cast(object, exc.detail)  # FastAPI accepts any JSON-able detail at runtime
    if isinstance(detail, dict):
        d = cast(dict[Any, Any], detail)
        message, fields = d.get("detail"), d.get("fields")
        return ApiErrorBody(
            detail=str(message) if message else _status_detail(exc.status_code),
            fields={str(k): str(v) for k, v in cast(dict[Any, Any], fields).items()}
            if isinstance(fields, dict)
            else None,
        )
    if isinstance(detail, str) and detail and detail != _reason_phrase(exc.status_code):
        return ApiErrorBody(detail=detail)
    return ApiErrorBody(detail=_status_detail(exc.status_code))


def _json(
    status: int, body: ApiErrorBody, headers: Mapping[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(
        body.model_dump(by_alias=True, exclude_none=True),
        status_code=status,
        headers=dict(headers) if headers else None,
    )


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    e = cast(StarletteHTTPException, exc)
    return _json(e.status_code, error_body(e), e.headers)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    e = cast(RequestValidationError, exc)
    return _json(422, ApiErrorBody(detail=VALIDATION_DETAIL, fields=validation_fields(e.errors())))


async def _unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    # The traceback goes to the log for operators; the client never sees internals.
    log.error("unhandled_error", path=request.url.path, exc_info=exc)
    return _json(500, ApiErrorBody(detail=INTERNAL_DETAIL))


def install(app: FastAPI) -> None:
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_exception_handler(Exception, _unhandled_error)
