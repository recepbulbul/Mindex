from collections.abc import Iterator
from datetime import date
from typing import Any, cast

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from db_support import database_url_for_tests, require_db
from mindex.api.app import create_app
from mindex.api.errors import INTERNAL_DETAIL, VALIDATION_DETAIL, validation_fields
from mindex.api.schemas import ApiModel
from mindex.db.models import Base
from mindex.db.session import get_session


class _Payload(ApiModel):
    start_date: date
    seed: int


def _app_with_probes() -> FastAPI:
    app = create_app()

    @app.post("/api/_probe")
    def probe(body: _Payload) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        return {"seed": body.seed}

    @app.get("/api/_conflict")
    def conflict() -> None:  # pyright: ignore[reportUnusedFunction]
        raise HTTPException(
            409, detail={"detail": "Ad kullanımda.", "fields": {"name": "Alınmış."}}
        )

    @app.get("/api/_boom")
    def boom() -> None:  # pyright: ignore[reportUnusedFunction]
        raise RuntimeError("secret internals")

    return app


def _probes() -> TestClient:
    return TestClient(_app_with_probes(), raise_server_exceptions=False)


class _BrokenSession:
    def execute(self, *_: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("down"))


def _broken_session() -> Iterator[Any]:
    yield _BrokenSession()


def test_health_is_503_without_database() -> None:
    app = create_app()
    app.dependency_overrides[get_session] = _broken_session
    res = TestClient(app).get("/api/health")
    assert res.status_code == 503
    assert res.json() == {"status": "degraded", "database": False}


def test_unknown_route_uses_turkish_envelope() -> None:
    res = TestClient(create_app()).get("/api/nope")
    assert res.status_code == 404
    assert res.json() == {"detail": "Kaynak bulunamadı."}


def test_validation_error_maps_camel_case_fields_in_turkish() -> None:
    res = _probes().post("/api/_probe", json={"seed": "x"})
    assert res.status_code == 422
    body = cast(dict[str, Any], res.json())
    assert body["detail"] == VALIDATION_DETAIL
    assert body["fields"] == {"startDate": "Zorunlu alan.", "seed": "Tam sayı olmalı."}


def test_camel_case_payload_is_accepted() -> None:
    res = _probes().post("/api/_probe", json={"startDate": "2025-10-01", "seed": 7})
    assert res.json() == {"seed": 7}


def test_structured_http_detail_keeps_status_and_fields() -> None:
    res = _probes().get("/api/_conflict")
    assert res.status_code == 409
    assert res.json() == {"detail": "Ad kullanımda.", "fields": {"name": "Alınmış."}}


def test_unhandled_error_is_a_json_500_without_internals() -> None:
    res = _probes().get("/api/_boom")
    assert res.status_code == 500
    assert res.json() == {"detail": INTERNAL_DETAIL}
    assert "secret" not in res.text


def test_validation_fields_keeps_first_message_and_own_messages() -> None:
    errors = [
        {"loc": ("body", "seed"), "type": "missing"},
        {"loc": ("body", "seed"), "type": "int_parsing"},
        {"loc": ("body",), "type": "something_new"},
        {
            "loc": ("body", "endDate"),
            "type": "value_error",
            "ctx": {"error": "Bitiş sonra olmalı."},
        },
    ]
    assert validation_fields(errors) == {
        "seed": "Zorunlu alan.",
        "body": "Geçersiz değer.",
        "endDate": "Bitiş sonra olmalı.",
    }


def test_openapi_is_served() -> None:
    res = TestClient(create_app()).get("/api/openapi.json")
    assert res.status_code == 200
    assert "/api/health" in res.json()["paths"]


def test_test_database_must_be_a_test_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MINDEX_TEST_DATABASE_URL", "postgresql+psycopg://u:p@127.0.0.1/mindex")
    with pytest.raises(RuntimeError, match="_test"):
        database_url_for_tests()


@pytest.mark.parametrize(
    ("value", "expected"), [("1", True), ("true", True), ("0", False), ("", False)]
)
def test_require_db_flag(monkeypatch: pytest.MonkeyPatch, value: str, expected: bool) -> None:
    monkeypatch.setenv("MINDEX_REQUIRE_DB", value)
    assert require_db() is expected


@pytest.mark.db
def test_health_ok_with_database(client: TestClient) -> None:
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": True}


@pytest.mark.db
def test_migrations_match_models(db_engine: Engine) -> None:
    """Alembic head and the ORM models agree on tables, columns, types, indexes, FKs and
    unique constraints. `compare_metadata` does not compare CHECK constraints or server
    defaults; those are covered by the constraint-name test below and by review."""
    with db_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


@pytest.mark.db
def test_check_constraints_match_models(db_session: Session) -> None:
    rows = db_session.execute(
        text("SELECT conname FROM pg_constraint WHERE contype = 'c' AND conname LIKE 'ck_%'")
    ).scalars()
    expected = {
        str(c.name)
        for t in Base.metadata.tables.values()
        for c in t.constraints
        if c.__class__.__name__ == "CheckConstraint"
    }
    assert set(rows) == expected


@pytest.mark.db
def test_assets_are_seeded(db_session: Session) -> None:
    symbols = db_session.execute(text("SELECT symbol FROM assets ORDER BY symbol")).scalars()
    assert list(symbols) == ["BNB", "BTC", "ETH", "SOL", "XRP"]
