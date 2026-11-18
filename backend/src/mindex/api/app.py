"""FastAPI application factories. Run locally: `uv run mindex serve`.

`create_app()` is the API alone (tests, OpenAPI); `create_server_app()` also starts the
in-process experiment runner and resumes runs a previous process left unfinished (NF2).
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from mindex import __version__
from mindex.api import errors
from mindex.api.routers import agents, auth, experiments, results
from mindex.api.schemas import ApiErrorBody, ExperimentUpdate, Health
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


# Every error is the `{detail, fields?}` envelope (`errors.install`); say so in the schema, so
# the generated frontend types cover it. 422 replaces FastAPI's own validation-error model.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    code: {"model": ApiErrorBody, "description": text}
    for code, text in {
        401: "Oturum gerekli",
        403: "Yetki yok",
        404: "Bulunamadı",
        409: "Durumla çakışıyor",
        422: "Geçersiz veri",
    }.items()
}
# Models the routes do not reference directly but the schema documents (PATCH's body).
SCHEMA_ONLY_MODELS = (ExperimentUpdate,)


def _with_schema_only_models(app: FastAPI) -> None:
    build = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = build()
        components = schema.setdefault("components", {}).setdefault("schemas", {})
        for model in SCHEMA_ONLY_MODELS:
            js = model.model_json_schema(by_alias=True, ref_template="#/components/schemas/{model}")
            for name, sub in js.pop("$defs", {}).items():
                components.setdefault(name, sub)
            components.setdefault(model.__name__, js)
        return schema

    app.openapi = openapi


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
    for router in (auth.router, agents.router, experiments.router, results.router):
        app.include_router(router, prefix=API_PREFIX, responses=ERROR_RESPONSES)
    _with_schema_only_models(app)
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
