"""`/experiments`: create, read, edit, delete, and YAML export/import of configurations (F2).

Reads need a session; writes need the researcher role. A period that touches the sealed test
window is refused here, on the server, whatever the client shows (look-ahead protocol).
"""

import uuid
from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Annotated, Any, cast

import yaml
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import ValidationError
from sqlalchemy import CursorResult, select, update

from mindex.agents.llm import PROMPT_VERSION
from mindex.api.deps import CurrentUser, JobQueueDep, Researcher, SessionDep, SettingsDep
from mindex.api.errors import validation_fields
from mindex.api.schemas import ExperimentCreate, ExperimentOut
from mindex.config import Settings
from mindex.data.splits import SPLITS, Split
from mindex.db.models import AgentKindDb, AgentRow, Experiment, ExperimentAgent, ExperimentStatus
from mindex.services.runner import ERROR as RUN_ERROR
from mindex.services.runner import STARTABLE, agent_rows, runnable_errors

router = APIRouter(prefix="/experiments", tags=["experiments"])

NOT_FOUND = "Deney bulunamadı."
INVALID_CONFIG = "Geçersiz deney yapılandırması."
NOT_EDITABLE = "Yalnızca taslak deneyler düzenlenebilir."
BAD_YAML = "YAML dosyası okunamadı."
NOT_STARTABLE = '"{status}" durumundaki deney başlatılamaz.'
NOT_RUNNABLE = "Deney bu koşucuda başlatılamaz."
PPO_UNAVAILABLE = "PPO ajanı eğitilmiş model ister; bu sunucuda MINDEX_PPO_MODEL_DIR ayarlı değil."
TEST_WINDOW = SPLITS[Split.TEST]
SEALED = (
    f"Dönem test penceresiyle ({TEST_WINDOW.start} – {TEST_WINDOW.end}) çakışıyor; "  # noqa: RUF001
    "test seti yalnızca nihai değerlendirmede açılır."
)
DELETABLE = {ExperimentStatus.DRAFT, ExperimentStatus.COMPLETED, ExperimentStatus.FAILED}
MAX_YAML_BYTES = 64 * 1024
COMMISSION_SCALE = 5  # Numeric(6, 5)
SLIPPAGE_SCALE = 2  # Numeric(6, 2)
YAML_HEADER = "# Mindex deney yapılandırması (F2)\n"
YAML_KEYS = {"name", "mode", "condition", "period", "assets", "agents", "seed", "execution", "llm"}


def _invalid(fields: Mapping[str, str], detail: str = INVALID_CONFIG) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT, {"detail": detail, "fields": dict(fields)}
    )


def overlaps_test_window(start: date, end: date | None) -> bool:
    """Same rule as the frontend's `overlapsTestWindow`: an open end runs into the window."""
    return start <= TEST_WINDOW.end and (end or date.max) >= TEST_WINDOW.start


def parse_config(data: Mapping[str, Any]) -> ExperimentCreate:
    """Validate a configuration that did not arrive as a request body (PATCH merge, YAML)."""
    try:
        return ExperimentCreate.model_validate(data)
    except ValidationError as exc:
        errs = [{**e, "loc": ("body", *e["loc"])} for e in exc.errors()]
        raise _invalid(validation_fields(errs)) from None


def check_config(cfg: ExperimentCreate, agents: Mapping[str, AgentRow], settings: Settings) -> None:
    """The rules that need the whole configuration: the form's two refinements, known and
    distinct agents, agents this server can build, and the sealed test window."""
    known_agents = list(agents)
    if cfg.mode == "replay" and cfg.end_date is None:
        raise _invalid({"endDate": "Replay modunda bitiş tarihi zorunlu"})
    if cfg.end_date is not None and cfg.end_date <= cfg.start_date:
        raise _invalid({"endDate": "Bitiş, başlangıçtan sonra olmalı"})
    unknown = next((a for a in cfg.agent_ids if a not in known_agents), None)
    if unknown is not None:
        raise _invalid({"agentIds": f"Bilinmeyen ajan: {unknown}"})
    if len(set(cfg.agent_ids)) != len(cfg.agent_ids):
        raise _invalid({"agentIds": "Aynı ajan birden fazla seçilmiş."})
    # Refused here, not half-way through a run: the PPO agent needs a trained artefact.
    if settings.ppo_model_dir is None and any(
        agents[a].kind is AgentKindDb.RL for a in cfg.agent_ids
    ):
        raise _invalid({"agentIds": PPO_UNAVAILABLE})
    if overlaps_test_window(cfg.start_date, cfg.end_date):
        field = (
            "endDate"
            if cfg.end_date is not None and cfg.start_date < TEST_WINDOW.start
            else "startDate"
        )
        raise _invalid({field: SEALED})


def _agents_by_slug(session: SessionDep) -> dict[str, AgentRow]:
    return {a.slug: a for a in session.scalars(select(AgentRow))}


def _out(exp: Experiment) -> ExperimentOut:
    return ExperimentOut(
        id=str(exp.id),
        name=exp.name,
        mode=exp.mode,
        condition=exp.condition,
        status=exp.status,
        start_date=exp.start_date,
        end_date=exp.end_date,
        assets=exp.assets,  # pyright: ignore[reportArgumentType] (validated into Asset)
        agent_ids=cast(list[str], exp.config["agentIds"]),
        seed=exp.seed,
        commission_rate=float(exp.commission_rate),
        slippage_bps=float(exp.slippage_bps),
        model_version=exp.model_version,
        prompt_version=exp.prompt_version,
        created_at=exp.created_at,
        error=cast(str | None, exp.config.get(RUN_ERROR)),
    )


CONFIG_FIELDS = {f.alias or name for name, f in ExperimentCreate.model_fields.items()}


def user_config(exp: Experiment) -> dict[str, Any]:
    """The configuration the user chose, without what the runner adds (`regime_source`...)."""
    return {k: v for k, v in exp.config.items() if k in CONFIG_FIELDS}


def user_config_with_runner_keys(exp: Experiment) -> dict[str, Any]:
    """`config` for a new start: everything but the previous run's error."""
    return {k: v for k, v in exp.config.items() if k != RUN_ERROR}


def config_of(exp: Experiment) -> ExperimentCreate:
    return ExperimentCreate.model_validate(user_config(exp))


def _apply(exp: Experiment, cfg: ExperimentCreate, agents: Mapping[str, AgentRow]) -> None:
    """Write a validated configuration onto the row and its agent links.

    Costs are rounded to the columns' scale first, so the row, `config`, the API response
    and the YAML export all carry the same values.
    """
    cfg = cfg.model_copy(
        update={
            "commission_rate": round(cfg.commission_rate, COMMISSION_SCALE),
            "slippage_bps": round(cfg.slippage_bps, SLIPPAGE_SCALE),
        }
    )
    exp.name = cfg.name
    exp.mode = cfg.mode
    exp.condition = cfg.condition
    exp.start_date = cfg.start_date
    exp.end_date = cfg.end_date
    exp.assets = [str(a) for a in cfg.assets]
    exp.seed = cfg.seed
    exp.commission_rate = Decimal(str(cfg.commission_rate))
    exp.slippage_bps = Decimal(str(cfg.slippage_bps))
    # `agentIds` keeps the chosen order; `experiment_agents` has none.
    exp.config = cfg.model_dump(mode="json", by_alias=True)
    wanted = {agents[s].id for s in cfg.agent_ids}
    exp.agents = [ea for ea in exp.agents if ea.agent_id in wanted]
    have = {ea.agent_id for ea in exp.agents}
    exp.agents += [
        ExperimentAgent(agent=agents[s]) for s in cfg.agent_ids if agents[s].id not in have
    ]


def get_experiment_row(session: SessionDep, experiment_id: str) -> Experiment:
    try:
        key = uuid.UUID(experiment_id)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND) from None
    exp = session.get(Experiment, key)
    if exp is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, NOT_FOUND)
    return exp


def _create(
    session: SessionDep, settings: SettingsDep, user: Researcher, cfg: ExperimentCreate
) -> ExperimentOut:
    agents = _agents_by_slug(session)
    check_config(cfg, agents, settings)
    exp = Experiment(
        owner_id=user.id,
        status=ExperimentStatus.DRAFT,
        model_version=settings.llm_model,
        prompt_version=PROMPT_VERSION,
    )
    _apply(exp, cfg, agents)
    session.add(exp)
    session.commit()
    session.refresh(exp)
    return _out(exp)


@router.get("")
def list_experiments(session: SessionDep, _: CurrentUser) -> list[ExperimentOut]:
    rows = session.scalars(select(Experiment).order_by(Experiment.created_at.desc()))
    return [_out(e) for e in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_experiment(
    body: ExperimentCreate, session: SessionDep, settings: SettingsDep, user: Researcher
) -> ExperimentOut:
    return _create(session, settings, user, body)


async def _yaml_body(request: Request) -> bytes:
    # Read here so the endpoint stays a sync `def` (its database calls run in the threadpool).
    raw = await request.body()
    if len(raw) > MAX_YAML_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE)
    return raw


@router.post(
    "/import",
    status_code=status.HTTP_201_CREATED,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/yaml": {"schema": {"type": "string"}}},
        }
    },
)
def import_experiment(
    raw: Annotated[bytes, Depends(_yaml_body)],
    session: SessionDep,
    settings: SettingsDep,
    user: Researcher,
) -> ExperimentOut:
    """A configuration exported by `export.yaml` becomes a new draft. `llm.*` is ignored:
    the draft is stamped with the model and prompt this server will run."""
    return _create(session, settings, user, parse_config(config_from_yaml(raw)))


@router.get("/{experiment_id}")
def get_experiment(experiment_id: str, session: SessionDep, _: CurrentUser) -> ExperimentOut:
    return _out(get_experiment_row(session, experiment_id))


@router.patch(
    "/{experiment_id}",
    responses={status.HTTP_409_CONFLICT: {"description": NOT_EDITABLE}},
)
def update_experiment(
    experiment_id: str,
    body: dict[str, Any],
    session: SessionDep,
    settings: SettingsDep,
    _: Researcher,
) -> ExperimentOut:
    """Partial `ExperimentCreate`; the merged configuration is validated as a whole."""
    exp = get_experiment_row(session, experiment_id)
    if exp.status is not ExperimentStatus.DRAFT:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_EDITABLE)
    unknown = sorted(k for k in body if k not in CONFIG_FIELDS)
    if unknown:
        raise _invalid(dict.fromkeys(unknown, "Bilinmeyen alan."))
    cfg = parse_config({**user_config(exp), **body})
    agents = _agents_by_slug(session)
    check_config(cfg, agents, settings)
    _apply(exp, cfg, agents)
    session.commit()
    session.refresh(exp)
    return _out(exp)


@router.delete(
    "/{experiment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses={status.HTTP_409_CONFLICT: {"description": "Koşan deney silinemez"}},
)
def delete_experiment(experiment_id: str, session: SessionDep, _: Researcher) -> Response:
    exp = get_experiment_row(session, experiment_id)
    if exp.status not in DELETABLE:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f'"{exp.status}" durumundaki deney silinemez.'
        )
    session.delete(exp)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{experiment_id}/start",
    responses={
        status.HTTP_409_CONFLICT: {"description": "Deney bu durumda başlatılamaz"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: {"description": "Koşucu bu deneyi çalıştıramaz"},
    },
)
def start_experiment(
    experiment_id: str,
    session: SessionDep,
    settings: SettingsDep,
    _: Researcher,  # before the queue: no session is 401, not "runner down"
    jobs: JobQueueDep,
) -> ExperimentOut:
    """Queue a draft or failed experiment for the in-process runner (a failed one resumes
    from its checkpoint); answers `queued`."""
    exp = get_experiment_row(session, experiment_id)
    if exp.status not in STARTABLE:
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_STARTABLE.format(status=exp.status))
    errors = runnable_errors(exp, [ea.agent for ea in agent_rows(exp)], settings)
    if errors:
        raise _invalid(errors, NOT_RUNNABLE)
    # Claimed in SQL, so two concurrent starts cannot both queue the same experiment.
    claimed: CursorResult[Any] = session.execute(  # pyright: ignore[reportAssignmentType]
        update(Experiment)
        .where(Experiment.id == exp.id, Experiment.status.in_(STARTABLE))
        .values(status=ExperimentStatus.QUEUED, config=user_config_with_runner_keys(exp))
    )
    if not claimed.rowcount:
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, NOT_STARTABLE.format(status=exp.status))
    session.commit()
    session.refresh(exp)
    jobs.submit(exp.id)
    return _out(exp)


@router.get(
    "/{experiment_id}/export.yaml",
    response_class=Response,
    responses={200: {"content": {"application/yaml": {"schema": {"type": "string"}}}}},
)
def export_experiment(experiment_id: str, session: SessionDep, _: CurrentUser) -> Response:
    exp = get_experiment_row(session, experiment_id)
    return Response(experiment_to_yaml(exp), media_type="application/yaml")


# ---------------------------------------------------------------- YAML


def experiment_to_yaml(exp: Experiment) -> str:
    cfg = config_of(exp)
    doc: dict[str, Any] = {
        "name": cfg.name,
        "mode": str(cfg.mode),
        "condition": str(cfg.condition),
        "period": {"start": cfg.start_date, "end": cfg.end_date},
        "assets": [str(a) for a in cfg.assets],
        "agents": list(cfg.agent_ids),
        "seed": cfg.seed,
        "execution": {
            "commission_rate": cfg.commission_rate,
            "slippage_bps": cfg.slippage_bps,
        },
        "llm": {"model": exp.model_version, "prompt_version": exp.prompt_version},
    }
    return YAML_HEADER + yaml.safe_dump(doc, allow_unicode=True, sort_keys=False)


def _section(doc: Mapping[str, Any], key: str, keys: set[str]) -> Mapping[str, Any]:
    value = doc.get(key, {})
    if not isinstance(value, dict):
        raise _invalid({key: "Eşleme olmalı."}, BAD_YAML)
    section = cast(dict[str, Any], value)
    extra = sorted(str(k) for k in section if k not in keys)
    if extra:
        raise _invalid({f"{key}.{k}": "Bilinmeyen alan." for k in extra}, BAD_YAML)
    return section


def config_from_yaml(raw: bytes) -> dict[str, Any]:
    """Map the export layout back to `ExperimentCreate` fields (values are validated later)."""
    try:
        loaded = yaml.safe_load(raw)
    except yaml.YAMLError:
        raise _invalid({"body": "Geçerli bir YAML belgesi olmalı."}, BAD_YAML) from None
    if not isinstance(loaded, dict):
        raise _invalid({"body": "Deney yapılandırması bir eşleme olmalı."}, BAD_YAML)
    doc = cast(dict[str, Any], loaded)
    extra = sorted(str(k) for k in doc if k not in YAML_KEYS)
    if extra:
        raise _invalid(dict.fromkeys(extra, "Bilinmeyen alan."), BAD_YAML)
    period = _section(doc, "period", {"start", "end"})
    execution = _section(doc, "execution", {"commission_rate", "slippage_bps"})
    _section(doc, "llm", {"model", "prompt_version"})
    fields = {
        "name": doc.get("name"),
        "mode": doc.get("mode"),
        "condition": doc.get("condition"),
        "startDate": period.get("start"),
        "endDate": period.get("end"),
        "assets": doc.get("assets"),
        "agentIds": doc.get("agents"),
        "seed": doc.get("seed"),
        "commissionRate": execution.get("commission_rate"),
        "slippageBps": execution.get("slippage_bps"),
    }
    # A missing key is reported as "Zorunlu alan."; only the end date may be null.
    return {k: v for k, v in fields.items() if v is not None or k == "endDate"}
