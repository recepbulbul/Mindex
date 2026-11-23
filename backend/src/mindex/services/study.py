"""Studies (#54): create, queue and compare every condition x seed of one configuration.

Shared by the API (`/studies`) and the CLI (`mindex study ...`). A study's experiments are
ordinary experiments with `study_id` set, so the runner, resumption (NF2) and every read
endpoint work on them unchanged. The comparison reads the completed runs' checkpoints (full
float precision, as the report does) and their recorded post-mortem checks.
"""

import json
import uuid
from collections import OrderedDict, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from statistics import fmean
from typing import cast

from sqlalchemy import func, select, update
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
    DecisionForumRead,
    DecisionRow,
    Experiment,
    ExperimentAgent,
    ExperimentMode,
    ExperimentStatus,
    Study,
)
from mindex.domain.metrics import herd_correlation
from mindex.evaluation.bootstrap import RESAMPLES, bootstrap_sharpe
from mindex.evaluation.report import daily_returns, differences, summarise
from mindex.services.runner import (
    ACTIVE,
    STARTABLE,
    agent_rows,
    lesson_consistency,
    runnable_errors,
)
from mindex.sim.engine import SimState

# Draft or failed runs are (re)queued; queued or running ones a stopped command left behind
# are run again from their checkpoint.
RESUMABLE = (*STARTABLE, ExperimentStatus.QUEUED, ExperimentStatus.RUNNING)
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


class StudyMismatchError(RuntimeError):
    """A run of the study no longer has the study's period, assets or agents."""


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


def agent_ids(exp: Experiment) -> list[str]:
    return cast(list[str], exp.config["agentIds"])


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
    return them, with the runs already queued or running, in run order: a command that stopped
    (a failed run, a killed process) leaves those behind, and starting again picks them up.
    Running one twice is harmless: the runner's advisory lock lets one worker run it and a
    finished run is not rerun. The caller submits them to a queue or runs them. Refused as a
    whole (422) when the runner cannot run one of them.

    The claim is a conditional UPDATE (as `POST /experiments/:id/start`): a run another worker
    finished or started after the listing is never set back to `queued`, and only runs still
    queued or running after the claim are returned."""
    runs = [e for e in study_runs(session, study) if e.status in RESUMABLE]
    for exp in runs:
        errors = runnable_errors(exp, [ea.agent for ea in agent_rows(exp)], settings)
        if errors:
            raise invalid(errors, NOT_RUNNABLE)
    for exp in runs:
        if exp.status in STARTABLE:
            session.execute(
                update(Experiment)
                .where(Experiment.id == exp.id, Experiment.status.in_(STARTABLE))
                .values(status=ExperimentStatus.QUEUED, config=user_config_with_runner_keys(exp))
            )
    session.commit()
    ids = [e.id for e in runs]
    active = set(
        session.scalars(
            select(Experiment.id).where(Experiment.id.in_(ids), Experiment.status.in_(ACTIVE))
        )
    )
    session.expire_all()  # the ORM copies of the claimed rows are stale now
    return [i for i in ids if i in active]


def _summary_inputs(
    exp: Experiment,
) -> tuple[list[list[float]], list[tuple[float, float]], float | None]:
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
    herd = herd_correlation(changes) if len(changes) >= 2 and len(changes[0]) >= 2 else None
    return series, risk, herd


@dataclass(frozen=True, slots=True)
class _Run:
    """One completed run's inputs to the comparison."""

    condition: Condition
    seed: int
    series: list[list[float]]  # daily returns per LLM agent
    risk: list[tuple[float, float]]  # (max drawdown, total return) per LLM agent
    herd: float | None  # None below two LLM agents
    checks: tuple[int, int]  # (valid, consistent) post-mortem attempts
    forum_weight: float | None  # mean sender weight w the run's decisions read (None: no reads)


# Bootstrapping 2000 resamples per request is the slow part: results are kept per study and
# per state of its runs (any status, checkpoint or configuration change gives a new key).
_CACHE: OrderedDict[tuple[object, ...], StudyComparisonOut] = OrderedDict()
CACHE_SIZE = 32


def _signature(
    study: Study, runs: Sequence[Experiment], resamples: int | None
) -> tuple[object, ...]:
    return (
        study.id,
        resamples,
        tuple(
            (
                e.id,
                e.status,
                e.last_checkpoint_day,
                e.start_date,
                e.end_date,
                tuple(e.assets),
                tuple(agent_ids(e)),
                lesson_consistency(e.config),
            )
            for e in runs
        ),
    )


def compare(
    session: Session, study: Study, *, resamples: int | None = None
) -> StudyComparisonOut | None:
    """The condition table over the completed runs; None before any run has completed.

    Each difference uses only the seeds both conditions completed, so a partial study never
    compares C3's k seeds with C0's k + 1. Cached per state of the study's runs."""
    runs = study_runs(session, study)
    key = _signature(study, runs, resamples)
    if key in _CACHE:
        _CACHE.move_to_end(key)
        return _CACHE[key]
    result = _compare(study, runs, resamples, _forum_weights(session, runs))
    if result is not None:
        _CACHE[key] = result
        while len(_CACHE) > CACHE_SIZE:
            _CACHE.popitem(last=False)
    return result


def _forum_weights(session: Session, runs: Sequence[Experiment]) -> dict[uuid.UUID, float]:
    """Mean `decision_forum_reads.weight` per run that read the forum."""
    rows = session.execute(
        select(ExperimentAgent.experiment_id, func.avg(DecisionForumRead.weight))
        .join(DecisionRow, DecisionRow.experiment_agent_id == ExperimentAgent.id)
        .join(DecisionForumRead, DecisionForumRead.decision_id == DecisionRow.id)
        .where(ExperimentAgent.experiment_id.in_([e.id for e in runs]))
        .group_by(ExperimentAgent.experiment_id)
    ).all()
    return {experiment_id: float(mean) for experiment_id, mean in rows}


def _compare(
    study: Study,
    runs: Sequence[Experiment],
    resamples: int | None,
    forum_weights: dict[uuid.UUID, float],
) -> StudyComparisonOut | None:
    done = [e for e in runs if e.status is ExperimentStatus.COMPLETED and e.checkpoint is not None]
    if not done:
        return None
    cfg = StudyCreate.model_validate(study.config)
    by_condition: dict[Condition, list[_Run]] = defaultdict(list)
    for exp in done:
        if (exp.start_date, exp.end_date, exp.assets, agent_ids(exp)) != (
            cfg.start_date,
            cfg.end_date,
            [str(a) for a in cfg.assets],
            cfg.agent_ids,
        ):
            raise StudyMismatchError(
                f"{exp.id}: dönem, varlık ya da ajanlar çalışmanınkinden farklı"
            )
        s, r, h = _summary_inputs(exp)
        by_condition[exp.condition].append(
            _Run(
                exp.condition,
                exp.seed,
                s,
                r,
                h,
                lesson_consistency(exp.config),
                forum_weights.get(exp.id),
            )
        )
    n = RESAMPLES if resamples is None else resamples

    def series(rows: Sequence[_Run]) -> list[list[float]]:
        return [x for run in rows for x in run.series]

    boot = bootstrap_sharpe({str(c): series(rows) for c, rows in by_condition.items()}, resamples=n)
    conditions: list[ConditionSummary] = []
    for c in CONDITIONS:
        rows = by_condition.get(c)
        if not rows:
            continue
        est = boot.sharpe[str(c)]
        read = [r.forum_weight for r in rows if r.forum_weight is not None]
        valid = sum(r.checks[0] for r in rows)
        consistent = sum(r.checks[1] for r in rows)
        conditions.append(
            ConditionSummary(
                condition=c,
                runs=len(rows),
                complete=all(
                    e.status is ExperimentStatus.COMPLETED for e in runs if e.condition is c
                ),
                sharpe_mean=est.value,
                sharpe_ci_low=est.ci_low,
                sharpe_ci_high=est.ci_high,
                max_drawdown=fmean(m for r in rows for m, _ in r.risk),
                total_return=fmean(t for r in rows for _, t in r.risk),
                herd_correlation=fmean(herds)
                if (herds := [r.herd for r in rows if r.herd is not None])
                else None,
                lesson_consistency=(
                    None if c is Condition.C0 or valid == 0 else consistent / valid
                ),
                mean_forum_weight=fmean(read) if read else None,
            )
        )
    differences: list[ConditionDifference] = []
    for a, b in PAIRS:
        seeds = {r.seed for r in by_condition.get(a, [])} & {
            r.seed for r in by_condition.get(b, [])
        }
        if not seeds:
            continue
        paired = bootstrap_sharpe(
            {str(c): series([r for r in by_condition[c] if r.seed in seeds]) for c in (a, b)},
            [(str(a), str(b))],
            resamples=n,
        )
        d = paired.differences[(str(a), str(b))]
        differences.append(
            ConditionDifference(
                condition=a,
                baseline=b,
                seeds=len(seeds),
                sharpe_diff=d.value,
                ci_low=d.ci_low,
                ci_high=d.ci_high,
            )
        )
    return StudyComparisonOut(
        study_id=str(study.id),
        complete=all(e.status is ExperimentStatus.COMPLETED for e in runs),
        days=boot.days,
        block_length=boot.block,
        resamples=boot.resamples,
        conditions=conditions,
        differences=differences,
    )


def get_study(session: Session, study_id: str) -> Study | None:
    try:
        key = uuid.UUID(study_id)
    except ValueError:
        return None
    return session.get(Study, key)
