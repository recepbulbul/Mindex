"""Test database helpers: a dedicated `<name>_test` database rebuilt once per test session.

Tests marked `db` need PostgreSQL + pgvector (`docker compose up -d db`, or the CI service).
They are skipped, not failed, when no database is reachable, so pure unit tests still run;
with `MINDEX_REQUIRE_DB=1` (CI) an unreachable database fails the run instead.
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
from mindex.db.session import CONNECT_TIMEOUT_SECONDS

BACKEND = Path(__file__).resolve().parents[1]
CONNECT_ARGS = {"connect_timeout": CONNECT_TIMEOUT_SECONDS}


def require_db() -> bool:
    return os.environ.get("MINDEX_REQUIRE_DB", "").strip().lower() in {"1", "true", "yes"}


def database_url_for_tests() -> str:
    explicit = os.environ.get("MINDEX_TEST_DATABASE_URL")
    if explicit:
        url = make_url(explicit)
    else:
        base = make_url(get_settings().database_url)
        url = base.set(database=f"{base.database}_test")
    # The database is dropped and recreated: never let that hit a non-test database.
    if not (url.database or "").endswith("_test"):
        raise RuntimeError(f"test database name must end with '_test', got {url.database!r}")
    return url.render_as_string(hide_password=False)


def _recreate_database(url: str) -> None:
    """Drop and create the test database so every session starts from a clean migration
    (an edited or branch-specific revision cannot leave a stale schema behind)."""
    target = make_url(url)
    admin = create_engine(
        target.set(database="postgres"), isolation_level="AUTOCOMMIT", connect_args=CONNECT_ARGS
    )
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{target.database}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        admin.dispose()


def alembic_config(url: str) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))  # ConfigParser interpolation
    cfg.attributes["configure_logger"] = False
    return cfg


def migrated_engine() -> Iterator[Engine]:
    url = database_url_for_tests()
    try:
        _recreate_database(url)
    except OperationalError as exc:
        if require_db():
            raise
        pytest.skip(f"PostgreSQL yok ({exc.__class__.__name__}); `docker compose up -d db`")
    command.upgrade(alembic_config(url), "head")
    engine = create_engine(url, connect_args=CONNECT_ARGS)
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
