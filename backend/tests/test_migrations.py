"""Alembic migrations that need data in place to be exercised (the schema itself is built by
`db_support.migrated_engine` once per session)."""

import pytest
from alembic import command
from sqlalchemy import Engine, text

from db_support import alembic_config

pytestmark = pytest.mark.db


def test_agent_seed_downgrade_with_experiments(db_engine: Engine) -> None:
    """0002's downgrade removes the seeded agents even when experiments use them: their
    `experiment_agents` links (and the run rows hanging off them) go first."""
    cfg = alembic_config(db_engine.url.render_as_string(hide_password=False))
    with db_engine.begin() as conn:
        owner = conn.execute(
            text(
                "INSERT INTO users (email, password_hash, role) "
                "VALUES ('migration@mindex.dev', 'x', 'researcher') RETURNING id"
            )
        ).scalar_one()
        exp = conn.execute(
            text(
                "INSERT INTO experiments (owner_id, name, mode, condition, start_date, end_date,"
                " assets, seed, config, model_version, prompt_version) VALUES (:o, 'Göç',"
                " 'replay', 'C0', '2025-10-01', '2025-11-01', ARRAY['BTC'], 1, '{}', 'm', 'p')"
                " RETURNING id"
            ),
            {"o": owner},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO experiment_agents (experiment_id, agent_id)"
                " SELECT :e, id FROM agents WHERE slug = 'ma-cross'"
            ),
            {"e": exp},
        )
    try:
        command.downgrade(cfg, "0001")
        with db_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM agents")).scalar_one() == 0
            links = "SELECT count(*) FROM experiment_agents WHERE experiment_id = :e"
            assert conn.execute(text(links), {"e": exp}).scalar_one() == 0
    finally:
        command.upgrade(cfg, "head")
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM experiments WHERE id = :e"), {"e": exp})
            conn.execute(text("DELETE FROM users WHERE id = :o"), {"o": owner})
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM agents")).scalar_one() == 9
