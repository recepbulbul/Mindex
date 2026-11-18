"""FastAPI application factory. Run locally: `uv run mindex serve` (or `uvicorn --factory`)."""

from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mindex import __version__
from mindex.api import errors
from mindex.api.schemas import Health
from mindex.db.session import get_session

API_PREFIX = "/api"

health_router = APIRouter(tags=["system"])


@health_router.get("/health")
def health(session: Annotated[Session, Depends(get_session)]) -> Health:
    try:
        session.execute(text("SELECT 1"))
        db_ok = True
    except SQLAlchemyError:
        db_ok = False
    return Health(status="ok" if db_ok else "degraded", database=db_ok)


def create_app() -> FastAPI:
    app = FastAPI(
        title="Mindex API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    errors.install(app)
    app.include_router(health_router, prefix=API_PREFIX)
    return app
