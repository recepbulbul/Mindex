from collections.abc import Iterator
from typing import Any, cast

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy import Engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from mindex.api.app import create_app
from mindex.api.errors import VALIDATION_DETAIL, validation_fields
from mindex.db.models import Base
from mindex.db.session import get_session


class _Payload(BaseModel):
    start_date: str
    seed: int


def _app_with_probe() -> FastAPI:
    app = create_app()

    @app.post("/api/_probe")
    def probe(body: _Payload) -> dict[str, int]:  # pyright: ignore[reportUnusedFunction]
        return {"seed": body.seed}

    return app


class _BrokenSession:
    def execute(self, *_: object) -> None:
        raise OperationalError("SELECT 1", {}, Exception("down"))


def _broken_session() -> Iterator[Any]:
    yield _BrokenSession()


def test_health_reports_degraded_without_database() -> None:
    app = create_app()
    app.dependency_overrides[get_session] = _broken_session
    res = TestClient(app).get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "degraded", "database": False}


def test_unknown_route_uses_error_envelope() -> None:
    res = TestClient(create_app()).get("/api/nope")
    assert res.status_code == 404
    assert res.json() == {"detail": "Not Found"}


def test_validation_error_maps_fields() -> None:
    res = TestClient(_app_with_probe()).post("/api/_probe", json={"seed": "x"})
    assert res.status_code == 422
    body = cast(dict[str, Any], res.json())
    assert body["detail"] == VALIDATION_DETAIL
    assert set(body["fields"]) == {"start_date", "seed"}


def test_validation_fields_keeps_first_message_per_field() -> None:
    errors = [
        {"loc": ("body", "seed"), "msg": "first"},
        {"loc": ("body", "seed"), "msg": "second"},
        {"loc": ("body",), "msg": "missing body"},
    ]
    assert validation_fields(errors) == {"seed": "first", "body": "missing body"}


def test_openapi_is_served() -> None:
    res = TestClient(create_app()).get("/api/openapi.json")
    assert res.status_code == 200
    assert "/api/health" in res.json()["paths"]


@pytest.mark.db
def test_health_ok_with_database(client: TestClient) -> None:
    assert client.get("/api/health").json() == {"status": "ok", "database": True}


@pytest.mark.db
def test_migrations_match_models(db_engine: Engine) -> None:
    """Alembic head and the ORM models describe the same schema (no forgotten migration)."""
    with db_engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


@pytest.mark.db
def test_assets_are_seeded(db_session: Session) -> None:
    symbols = db_session.execute(text("SELECT symbol FROM assets ORDER BY symbol")).scalars()
    assert list(symbols) == ["BNB", "BTC", "ETH", "SOL", "XRP"]
