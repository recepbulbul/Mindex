import math
from collections.abc import Iterator
from datetime import date, timedelta

import polars as pl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.orm import Session

from db_support import migrated_engine, transactional_session
from mindex.api.app import create_app
from mindex.data.snapshot import SCHEMA
from mindex.db.session import get_session
from mindex.domain.decision import Asset
from mindex.sim.market import MarketData

ASSETS = (Asset.BTC, Asset.ETH)


def synthetic_frame(start: date, days: int, assets: tuple[Asset, ...] = ASSETS) -> pl.DataFrame:
    """Deterministic price paths: BTC trends up, ETH oscillates, others drift down."""
    rows: list[dict[str, object]] = []
    for k, asset in enumerate(assets):
        for i in range(days):
            if k == 0:
                close = 100.0 * (1.01**i)
            elif k == 1:
                close = 50.0 + 10.0 * math.sin(i / 3)
            else:
                close = 20.0 * (0.995**i)
            open_ = close * 0.995
            rows.append(
                {
                    "asset": str(asset),
                    "day": start + timedelta(days=i),
                    "open": open_,
                    "high": max(open_, close) * 1.01,
                    "low": min(open_, close) * 0.99,
                    "close": close,
                    "volume": 1000.0 + i,
                    "fear_greed": 50 + i % 10,
                    "funding_rate": 0.0001,
                }
            )
    return pl.DataFrame(rows, schema=SCHEMA)


@pytest.fixture
def market() -> MarketData:
    return MarketData.from_frame(synthetic_frame(date(2025, 1, 1), 60))


@pytest.fixture(scope="session")
def db_engine() -> Iterator[Engine]:
    yield from migrated_engine()


@pytest.fixture
def db_session(db_engine: Engine) -> Iterator[Session]:
    for _, session in transactional_session(db_engine):
        yield session


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    """API client whose requests share the test's rolled-back session."""
    app = create_app()

    def session_override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as c:
        yield c
