"""Studies (#54): create, queue and compare every condition x seed of one configuration.

Shared by the API (`/studies`) and the CLI (`mindex study ...`). A study's experiments are
ordinary experiments with `study_id` set, so the runner, resumption (NF2) and every read
endpoint work on them unchanged. The comparison reads the completed runs' checkpoints (full
float precision, as the report does) and their recorded post-mortem checks.
"""

import json
import uuid
from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta
from statistics import fmean

from sqlalchemy import select
from sqlalchemy.orm import Session

from mindex.agents.llm import PROMPT_VERSION
from mindex.api.routers.experiments import (
    NOT_RUNNABLE,
    apply_config,
    check_config,
    invalid,
    user_config_with_runner_keys,
)
from mindex.api.schemas import (
    SMOKE_DAYS,
    ConditionDifference,
    ConditionSummary,
    ExperimentCreate,
    StudyComparisonOut,
    StudyCreate,
    StudyOut,
    StudyRunOut,
)
from mindex.config import Settings
from mindex.db.models import (
    AgentKindDb,
    AgentRow,
    Condition,
    Experiment,
    ExperimentMode,
    ExperimentStatus,
    Study,
)
from mindex.domain.metrics import herd_correlation
from mindex.evaluation.bootstrap import bootstrap_sharpe
from mindex.evaluation.report import daily_returns, differences, summarise
from mindex.services.runner import (
    STARTABLE,
    agent_rows,
    lesson_consistency,
    runnable_errors,
)
from mindex.sim.engine import SimState

CONDITIONS = tuple(Condition)  # C0, C1, C1_NO_REGIME, C2, C3: each run of a seed, in order
# Each ablation step on its own, and the whole: memory, regime bonus, forum, trust, all.
PAIRS: tuple[tuple[Condition, Condition], ...] = (
    (Condition.C1, Condition.C0),
    (Condition.C1, Condition.C1_NO_REGIME),
    (Condition.C2, Condition.C1),
    (Condition.C3, Condition.C2),
    (Condition.C3, Condition.C0),
)
CONDITION_NAMES = {
    Condition.C0: "C0",
    Condition.C1: "C1",
    Condition.C1_NO_REGIME: "C1′",  # noqa: RUF001 (the prime of the proposal's C1')
    Condition.C2: "C2",
    Condition.C3: "C3",
}
NEEDS_LLM = "Çalışma en az bir LLM ajanı ister: karşılaştırma LLM ajanlarının üzerinedir."
NOT_STARTABLE_RUNS = "Çalışmanın deneyleri bu koşucuda başlatılamaz."


def effective(cfg: StudyCreate) -> StudyCreate:
    """`smoke`: the first SMOKE_DAYS days and the first seed only."""
    if not cfg.smoke:
        return cfg
    end = min(cfg.end_date, cfg.start_date + timedelta(days=SMOKE_DAYS))
    return cfg.model_copy(update={"end_date": end, "seeds": cfg.seeds[:1]})


def experiment_config(cfg: StudyCreate, condition: Condition, seed: int) -> ExperimentCreate:
    return ExperimentCreate(
        name=f"{cfg.name} · {CONDITION_NAMES[condition]} · seed {seed}",
        mode=ExperimentMode.REPLAY,
        condition=condition,
        start_date=cfg.start_date,
        end_date=cfg.end_date,
        assets=cfg.assets,
        agent_ids=cfg.agent_ids,
        seed=seed,
        commission_rate=cfg.commission_rate,
        slippage_bps=cfg.slippage_bps,
    )


def create_study(
    session: Session, settings: Settings, owner_id: uuid.UUID, body: StudyCreate
) -> Study:
    """The study and its draft experiments, all or nothing. The sealed test window, unknown
    agents and agents this runner cannot run are refused (422) before anything is written."""
    cfg = effective(body)
    agents = {a.slug: a for a in session.scalars(select(AgentRow))}
    first = experiment_config(cfg, CONDITIONS[0], cfg.seeds[0])
    check_config(first, agents, settings)  # period, test window, known agents, PPO artefact
    if not any(agents[a].kind is AgentKindDb.LLM for a in cfg.agent_ids):
        raise invalid({"agentIds": NEEDS_LLM})
    study = Study(
        owner_id=owner_id, name=cfg.name, config=cfg.model_dump(mode="json", by_alias=True)
    )
    session.add(study)
    session.flush()
    for seed in cfg.seeds:
        for condition in CONDITIONS:
            exp = Experiment(
                owner_id=owner_id,
                study_id=study.id,
                status=ExperimentStatus.DRAFT,
                model_version=settings.llm_model,
                prompt_version=PROMPT_VERSION,
            )
            apply_config(exp, experiment_config(cfg, condition, seed), agents)
            errors = runnable_errors(exp, [agents[a] for a in cfg.agent_ids], settings)
            if errors:
                session.rollback()
                raise invalid(errors, NOT_STARTABLE_RUNS)
            session.add(exp)
    session.commit()
    session.refresh(study)
    return study


def study_runs(session: Session, study: Study) -> list[Experiment]:
    """Seed by seed, each seed's conditions in CONDITIONS order."""
    rows = list(session.scalars(select(Experiment).where(Experiment.study_id == study.id)))
    order = {c: i for i, c in enumerate(CONDITIONS)}
    return sorted(rows, key=lambda e: (e.seed, order[e.condition]))


def study_status(runs: Sequence[Experiment]) -> ExperimentStatus:
    statuses = {e.status for e in runs}
    if not statuses or statuses == {ExperimentStatus.DRAFT}:
        return ExperimentStatus.DRAFT
    if statuses == {ExperimentStatus.COMPLETED}:
        return ExperimentStatus.COMPLETED
    if ExperimentStatus.RUNNING in statuses:
        return ExperimentStatus.RUNNING
    if ExperimentStatus.QUEUED in statuses:
        return ExperimentStatus.QUEUED
    if ExperimentStatus.FAILED in statuses:
        return ExperimentStatus.FAILED
    return ExperimentStatus.RUNNING  # some completed, the rest drafts or paused: under way


def study_out(session: Session, study: Study) -> StudyOut:
    runs = study_runs(session, study)
    cfg = StudyCreate.model_validate(study.config)
    return StudyOut(
        id=str(study.id),
        name=study.name,
        start_date=cfg.start_date,
        end_date=cfg.end_date,
        assets=cfg.assets,
        agent_ids=cfg.agent_ids,
        seeds=cfg.seeds,
        smoke=cfg.smoke,
        commission_rate=cfg.commission_rate,
        slippage_bps=cfg.slippage_bps,
        status=study_status(runs),
        created_at=study.created_at,
        runs=[
            StudyRunOut(
                experiment_id=str(e.id),
                condition=e.condition,
                seed=e.seed,
                status=e.status,
                last_day=e.last_checkpoint_day,
            )
            for e in runs
        ],
    )


def queue_study(session: Session, settings: Settings, study: Study) -> list[uuid.UUID]:
    """Mark every draft or failed run `queued` (failed ones resume from their checkpoint) and
    return them in run order; the caller submits them to a queue or runs them. Refused as a
    whole (422) when the runner cannot run one of them."""
    runs = [e for e in study_runs(session, study) if e.status in STARTABLE]
    for exp in runs:
        errors = runnable_errors(exp, [ea.agent for ea in agent_rows(exp)], settings)
        if errors:
            raise invalid(errors, NOT_RUNNABLE)
    for exp in runs:
        exp.status = ExperimentStatus.QUEUED
        exp.config = user_config_with_runner_keys(exp)
    session.commit()
    return [e.id for e in runs]


def _summary_inputs(exp: Experiment) -> tuple[list[list[float]], list[tuple[float, float]], float]:
    """Per LLM agent: daily returns and (max drawdown, total return); and the run's herd
    correlation (LLM agents' daily changes in invested weight, as in the report)."""
    assert exp.checkpoint is not None  # noqa: S101 (completed runs have one)
    state = SimState.from_json(json.dumps(exp.checkpoint))
    llm = [ea.agent.slug for ea in agent_rows(exp) if ea.agent.kind is AgentKindDb.LLM]
    series: list[list[float]] = []
    risk: list[tuple[float, float]] = []
    for slug in llm:
        book = state.books[slug]
        s = summarise(slug, "llm", book)
        series.append(daily_returns(book.equity))
        risk.append((s.max_drawdown, s.total_return))
    changes = [differences(state.books[slug].invested) for slug in llm]
    herd = herd_correlation(changes) if len(changes) >= 2 and len(changes[0]) >= 2 else 0.0
    return series, risk, herd


def compare(
    session: Session, study: Study, *, resamples: int | None = None
) -> StudyComparisonOut | None:
    """The condition table over the completed runs; None before any run has completed."""
    runs = study_runs(session, study)
    done = [e for e in runs if e.status is ExperimentStatus.COMPLETED and e.checkpoint is not None]
    if not done:
        return None
    series: dict[Condition, list[list[float]]] = defaultdict(list)
    risk: dict[Condition, list[tuple[float, float]]] = defaultdict(list)
    herds: dict[Condition, list[float]] = defaultdict(list)
    checks: dict[Condition, list[tuple[int, int]]] = defaultdict(list)
    count: dict[Condition, int] = defaultdict(int)
    for exp in done:
        s, r, h = _summary_inputs(exp)
        series[exp.condition] += s
        risk[exp.condition] += r
        herds[exp.condition].append(h)
        checks[exp.condition].append(lesson_consistency(exp.config))
        count[exp.condition] += 1
    days = min(len(x) for rows in series.values() for x in rows)
    groups = {str(c): [x[:days] for x in rows] for c, rows in series.items()}
    boot = bootstrap_sharpe(
        groups,
        [(str(a), str(b)) for a, b in PAIRS],
        **({} if resamples is None else {"resamples": resamples}),
    )
    conditions: list[ConditionSummary] = []
    for c in CONDITIONS:
        if c not in series:
            continue
        est = boot.sharpe[str(c)]
        valid = sum(v for v, _ in checks[c])
        consistent = sum(k for _, k in checks[c])
        conditions.append(
            ConditionSummary(
                condition=c,
                runs=count[c],
                sharpe_mean=est.value,
                sharpe_ci_low=est.ci_low,
                sharpe_ci_high=est.ci_high,
                max_drawdown=fmean(m for m, _ in risk[c]),
                total_return=fmean(t for _, t in risk[c]),
                herd_correlation=fmean(herds[c]),
                lesson_consistency=(
                    None if c is Condition.C0 or valid == 0 else consistent / valid
                ),
            )
        )
    return StudyComparisonOut(
        study_id=str(study.id),
        complete=all(e.status is ExperimentStatus.COMPLETED for e in runs),
        days=boot.days,
        block_length=boot.block,
        resamples=boot.resamples,
        conditions=conditions,
        differences=[
            ConditionDifference(
                condition=Condition(a),
                baseline=Condition(b),
                sharpe_diff=d.value,
                ci_low=d.ci_low,
                ci_high=d.ci_high,
            )
            for (a, b), d in boot.differences.items()
        ],
    )


def get_study(session: Session, study_id: str) -> Study | None:
    try:
        key = uuid.UUID(study_id)
    except ValueError:
        return None
    return session.get(Study, key)
