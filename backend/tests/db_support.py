"""Test database helpers: a dedicated `<name>_test` database migrated once per session.

Tests marked `db` need PostgreSQL + pgvector (`docker compose up -d db`, or the CI service).
They are skipped, not failed, when no database is reachable, so pure unit tests still run.
"""

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, create_engine, make_url, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from mindex.config import get_settings

BACKEND = Path(__file__).resolve().parents[1]


def test_database_url() -> str:
    explicit = os.environ.get("MINDEX_TEST_DATABASE_URL")
    if explicit:
        return explicit
    url = make_url(get_settings().database_url)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def _ensure_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": target.database}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        admin.dispose()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url)
    cfg.attributes["configure_logger"] = False
    return cfg


def migrated_engine() -> Iterator[Engine]:
    url = test_database_url()
    try:
        _ensure_database(url)
    except OperationalError as exc:
        if os.environ.get("MINDEX_REQUIRE_DB"):
            raise
        pytest.skip(f"PostgreSQL yok ({exc.__class__.__name__}); `docker compose up -d db`")
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url)
    yield engine
    engine.dispose()


def transactional_session(engine: Engine) -> Iterator[tuple[Connection, Session]]:
    """A session whose commits become savepoints of one outer transaction rolled back after."""
    conn = engine.connect()
    outer = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        yield conn, session
    finally:
        session.close()
        outer.rollback()
        conn.close()
