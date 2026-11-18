"""FastAPI application factories. Run locally: `uv run mindex serve`.

`create_app()` is the API alone (tests, OpenAPI); `create_server_app()` also starts the
in-process experiment runner and resumes runs a previous process left unfinished (NF2).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mindex import __version__
from mindex.api import errors
from mindex.api.routers import agents, auth, experiments, results
from mindex.api.schemas import Health
from mindex.config import get_settings
from mindex.db.session import get_session, get_sessionmaker
from mindex.services.runner import ExperimentRunner, InProcessQueue, resume_interrupted

API_PREFIX = "/api"

health_router = APIRouter(tags=["system"])


@health_router.get("/health", responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": Health}})
def health(session: Annotated[Session, Depends(get_session)], response: Response) -> Health:
    """Liveness plus database reachability; 503 when degraded so monitors alert on it."""
    try:
        session.execute(text("SELECT 1"))
        db_ok = True
    except SQLAlchemyError:
        db_ok = False
    if not db_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return Health(status="ok" if db_ok else "degraded", database=db_ok)


def create_app(**kwargs: object) -> FastAPI:
    app = FastAPI(
        **kwargs,  # pyright: ignore[reportArgumentType]
        title="Mindex API",
        version=__version__,
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
    )
    errors.install(app)
    app.include_router(health_router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(agents.router, prefix=API_PREFIX)
    app.include_router(experiments.router, prefix=API_PREFIX)
    app.include_router(results.router, prefix=API_PREFIX)
    return app


@asynccontextmanager
async def _runner(app: FastAPI) -> AsyncGenerator[None]:
    sessions = get_sessionmaker()
    jobs = InProcessQueue(ExperimentRunner(sessions, get_settings()))
    app.state.job_queue = jobs
    resume_interrupted(sessions, jobs)
    try:
        yield
    finally:
        # The current day is committed or rolled back as a whole; restart resumes it.
        jobs.close(timeout=5)


def create_server_app() -> FastAPI:
    return create_app(lifespan=_runner)
