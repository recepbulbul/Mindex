"""In-process experiment runner (F2, NF2): a job queue, the day loop and resumable checkpoints.

`POST /experiments/:id/start` marks a draft `queued` and submits it to a `JobQueue`. The
worker replays the experiment day by day with `Simulator.step`; after every day the
decisions, fills and portfolio snapshots of that day *and* the simulator checkpoint are
committed in one transaction. A process that dies mid-day therefore loses only that day, and
on restart (`resume_interrupted`) the run continues from the checkpoint with the same result,
bit for bit, as an uninterrupted run. Any error marks the experiment `failed`.

Scope until later work packages (refused with an explicit message, never run silently):
- `live` mode (P7) and external MCP agents;
- LLM agents outside C0: memory and forum are not wired into `LLMAgent` yet;
- the PPO agent without a trained artefact (`MINDEX_PPO_MODEL_DIR`; training needs torch,
  which runs on the GPU machine).

Regimes come from the HMM artefact at `MINDEX_REGIME_MODEL_PATH`; without one every day is
labelled `sideways` (`PLACEHOLDER_REGIME`), a placeholder, not a measurement.

The queue lives in the API process (one worker thread): Redis Streams replace it in P6-P7
behind the same `JobQueue` protocol.
"""

import hashlib
import json
import queue
import threading
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, cast

import polars as pl
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from mindex.agents.base import BaseAgent
from mindex.agents.llm import PROMPT_VERSION, ChatClient, LlamaCppClient, LLMAgent
from mindex.agents.rule import BuyAndHoldAgent, EqualWeightAgent, MovingAverageCrossAgent
from mindex.config import Settings
from mindex.data.snapshot import load_split
from mindex.data.splits import SPLITS, ensure_readable
from mindex.db.models import (
    AgentKindDb,
    AgentRow,
    Condition,
    DecisionRow,
    Experiment,
    ExperimentAgent,
    ExperimentMode,
    ExperimentStatus,
    PortfolioSnapshot,
    TradeRow,
    TradeSide,
)
from mindex.domain.decision import Asset, Decision
from mindex.domain.regime import Regime
from mindex.sim.engine import ExecutionCosts, Observation, SimState, Simulator
from mindex.sim.market import MarketData

LOOKBACK_DAYS = 31  # indicator warm-up before the first decision day (30 returns, MA(30))
PLACEHOLDER_REGIME = Regime.SIDEWAYS
STARTABLE = (ExperimentStatus.DRAFT, ExperimentStatus.PAUSED)
ACTIVE = (ExperimentStatus.QUEUED, ExperimentStatus.RUNNING)

log = structlog.get_logger(__name__)

SessionFactory = Callable[[], Session]
ChatClientFactory = Callable[[Experiment], ChatClient]


class DataUnavailableError(RuntimeError):
    """The snapshot does not cover the experiment's period or assets."""


class UnsupportedExperimentError(ValueError):
    def __init__(self, fields: Mapping[str, str]) -> None:
        super().__init__("; ".join(f"{k}: {v}" for k, v in fields.items()))
        self.fields = dict(fields)


# ---------------------------------------------------------------- queue


class JobQueue(Protocol):
    def submit(self, experiment_id: uuid.UUID) -> None: ...


class InProcessQueue:
    """One daemon worker thread draining a FIFO of experiment ids."""

    def __init__(self, work: Callable[[uuid.UUID], None]) -> None:
        self._work = work
        self._jobs: queue.Queue[uuid.UUID | None] = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="mindex-runner", daemon=True)
        self._thread.start()

    def submit(self, experiment_id: uuid.UUID) -> None:
        self._jobs.put(experiment_id)

    def join(self) -> None:
        """Block until every submitted job has finished (tests, shutdown)."""
        self._jobs.join()

    def close(self, timeout: float | None = None) -> None:
        self._jobs.put(None)
        self._thread.join(timeout)

    def _loop(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                if job is None:
                    return
                self._work(job)
            except Exception:  # the runner marks failures itself; never kill the worker
                log.exception("runner_job_crashed", experiment_id=str(job))
            finally:
                self._jobs.task_done()


def resume_interrupted(sessions: SessionFactory, jobs: JobQueue) -> list[uuid.UUID]:
    """Resubmit experiments a previous process left queued or running (NF2)."""
    with sessions() as session:
        ids = list(session.scalars(select(Experiment.id).where(Experiment.status.in_(ACTIVE))))
    for experiment_id in ids:
        jobs.submit(experiment_id)
    if ids:
        log.info("runner_resumed", experiments=[str(i) for i in ids])
    return ids


# ---------------------------------------------------------------- market data


def load_market(
    snapshot_dir: Path, start: date, end: date, assets: Sequence[str]
) -> tuple[MarketData, int]:
    """Prices from `start - LOOKBACK_DAYS` to `end` for `assets`, plus the index of the first
    decision day. Every split the period touches goes through `ensure_readable`, so the
    sealed test split is refused here as well as in the API."""
    since = start - timedelta(days=LOOKBACK_DAYS)
    frames: list[pl.DataFrame] = []
    for split, window in SPLITS.items():
        if window.start <= end and window.end >= since:
            ensure_readable(split)
            frames.append(load_split(snapshot_dir, split))
    if not frames:
        raise DataUnavailableError("the snapshot has no split for this period")
    df = pl.concat(frames).filter(
        pl.col("day").is_between(since, end) & pl.col("asset").is_in(list(assets))
    )
    if df.is_empty():
        raise DataUnavailableError("the snapshot has no prices for this period")
    market = MarketData.from_frame(df)
    missing = set(assets) - {str(a) for a in market.assets}
    if missing:
        raise DataUnavailableError(f"the snapshot has no prices for {sorted(missing)}")
    first = next((i for i, d in enumerate(market.days) if d >= start), None)
    if first is None or first >= len(market) - 1:
        raise DataUnavailableError("the snapshot ends before the experiment's first day")
    return market, first


def experiment_market(exp: Experiment, settings: Settings) -> tuple[MarketData, int]:
    if exp.end_date is None:
        raise DataUnavailableError("open-ended (live) experiments have no replay period")
    return load_market(settings.snapshot_dir, exp.start_date, exp.end_date, exp.assets)


REGIME_SOURCE = "regime_source"  # `config` keys the runner adds (not part of the user's form)
REGIME_SHA256 = "regime_sha256"


def regime_provenance(settings: Settings) -> dict[str, str | None]:
    """Where an experiment's regime labels come from, recorded in its `config` (NF5): the
    HMM artefact's SHA-256 (as `RegimeModel.save` returns it), or the explicit placeholder."""
    path = settings.regime_model_path
    if path is None:
        return {REGIME_SOURCE: "placeholder", REGIME_SHA256: None}
    digest = hashlib.sha256(path.read_text(encoding="utf-8").encode()).hexdigest()
    return {REGIME_SOURCE: "hmm", REGIME_SHA256: digest}


def regime_labels(market: MarketData, settings: Settings) -> list[Regime]:
    """The HMM's filtered (no look-ahead) label per day, or the placeholder without a model."""
    if settings.regime_model_path is None:
        return [PLACEHOLDER_REGIME] * len(market)
    from mindex.regime.hmm import RegimeModel, regime_features

    return RegimeModel.load(settings.regime_model_path).label(regime_features(market))


# ---------------------------------------------------------------- agents


def agent_rows(exp: Experiment) -> list[ExperimentAgent]:
    """The experiment's agent links in the order the configuration lists them."""
    by_slug = {ea.agent.slug: ea for ea in exp.agents}
    return [by_slug[s] for s in cast(list[str], exp.config["agentIds"])]


def runnable_errors(
    exp: Experiment, agents: Sequence[AgentRow], settings: Settings
) -> dict[str, str]:
    """Why this runner cannot run `exp`, keyed by the configuration field to change."""
    errors: dict[str, str] = {}
    if exp.mode is ExperimentMode.LIVE:
        errors["mode"] = "Canlı mod koşucuda henüz desteklenmiyor (İP7)."
    problems: list[str] = []
    for a in agents:
        if a.kind is AgentKindDb.RL and settings.ppo_model_dir is None:
            problems.append(
                f"{a.slug}: PPO ajanı eğitilmiş model ister (MINDEX_PPO_MODEL_DIR ayarlı değil)"
            )
        elif a.kind is AgentKindDb.EXTERNAL:
            problems.append(f"{a.slug}: dış (MCP) ajanlar koşucuda henüz desteklenmiyor")
        elif a.params.get("rule") == "buy_and_hold" and a.params["asset"] not in exp.assets:
            problems.append(f"{a.slug}: varlıklarda {a.params['asset']} olmalı")
    if problems:
        errors["agentIds"] = "; ".join(problems) + "."
    if any(a.kind is AgentKindDb.LLM for a in agents):
        if exp.condition is not Condition.C0:
            errors["condition"] = (
                "LLM ajanları şimdilik yalnızca C0'da koşar; hafıza ve forum bağlantısı "
                "sonraki iş paketinde."
            )
        if exp.prompt_version != PROMPT_VERSION:
            errors["promptVersion"] = (
                f"Deney {exp.prompt_version} prompt'uyla kaydedilmiş; bu sunucu "
                f"{PROMPT_VERSION} çalıştırır."
            )
    return errors


def llama_cpp_clients(settings: Settings) -> ChatClientFactory:
    """The production client: the experiment's model and seed on the configured llama-server."""

    def make(exp: Experiment) -> ChatClient:
        return LlamaCppClient(
            settings.llm_base_url,
            exp.model_version,
            timeout=settings.llm_timeout_seconds,
            seed=exp.seed,
        )

    return make


def build_agent(
    row: AgentRow, exp: Experiment, settings: Settings, chat_client: ChatClientFactory
) -> BaseAgent:
    params = row.params
    match row.kind, params.get("rule"):
        case AgentKindDb.RULE, "buy_and_hold":
            return BuyAndHoldAgent(Asset(params["asset"]), agent_id=row.slug)
        case AgentKindDb.RULE, "equal_weight":
            return EqualWeightAgent(int(params["rebalance_days"]), agent_id=row.slug)
        case AgentKindDb.RULE, "ma_cross":
            return MovingAverageCrossAgent(
                int(params["short"]), int(params["long"]), agent_id=row.slug
            )
        case AgentKindDb.LLM, _:
            return LLMAgent(
                chat_client(exp),
                persona=str(params["persona"]),
                max_retries=settings.llm_max_retries,
                agent_id=row.slug,
            )
        case AgentKindDb.RL, _ if settings.ppo_model_dir is not None:
            from mindex.agents.ppo import PPOAgent  # loads SB3/torch only when used

            return PPOAgent.from_artifact(settings.ppo_model_dir, agent_id=row.slug)
        case _:
            raise UnsupportedExperimentError({"agentIds": f"{row.slug}: koşucu bu ajanı kuramaz"})


@dataclass(frozen=True, slots=True)
class Recorded:
    decision: Decision | None
    weights: dict[Asset, float]  # before the decision (what a hold keeps)
    attempts: int
    latency_ms: int


class RecordingAgent:
    """Passes decisions through unchanged and remembers the last one for the database."""

    def __init__(self, inner: BaseAgent) -> None:
        self.inner = inner
        self.last: Recorded | None = None

    @property
    def agent_id(self) -> str:
        return self.inner.agent_id

    def decide(self, obs: Observation) -> Decision | None:
        started = time.perf_counter()
        decision = self.inner.decide(obs)
        latency = round((time.perf_counter() - started) * 1000)
        attempts = self.inner.stats.attempts[-1] if isinstance(self.inner, LLMAgent) else 1
        self.last = Recorded(decision, dict(obs.weights), attempts, latency)
        return decision


# ---------------------------------------------------------------- runner


def _money(x: float) -> Decimal:
    return Decimal(str(round(x, 2)))


def _midnight(day: date) -> datetime:
    return datetime.combine(day, dtime(0), tzinfo=UTC)  # orders execute at the daily open


class ExperimentRunner:
    """The queue's worker: `runner(experiment_id)` runs (or resumes) one experiment."""

    def __init__(
        self,
        sessions: SessionFactory,
        settings: Settings,
        chat_client: ChatClientFactory | None = None,
    ) -> None:
        self.sessions = sessions
        self.settings = settings
        self.chat_client = chat_client or llama_cpp_clients(settings)

    def __call__(self, experiment_id: uuid.UUID) -> None:
        self.run(experiment_id)

    def run(self, experiment_id: uuid.UUID, *, max_days: int | None = None) -> None:
        """Run until the end, or stop after `max_days` days (status stays `running`, as if the
        process had stopped; the next `run` resumes from the checkpoint)."""
        try:
            self._run(experiment_id, max_days)
        except Exception as exc:
            log.error("experiment_failed", experiment_id=str(experiment_id), exc_info=exc)
            with self.sessions() as session:
                exp = session.get(Experiment, experiment_id)
                if exp is not None:
                    exp.status = ExperimentStatus.FAILED
                    session.commit()

    def _run(self, experiment_id: uuid.UUID, max_days: int | None) -> None:
        with self.sessions() as session:
            exp = session.get(Experiment, experiment_id)
            if exp is None or exp.status not in ACTIVE:
                return  # deleted, or already finished by an earlier worker
            links = agent_rows(exp)
            errors = runnable_errors(exp, [ea.agent for ea in links], self.settings)
            if errors:
                raise UnsupportedExperimentError(errors)

            market, start = experiment_market(exp, self.settings)
            agents = [
                RecordingAgent(build_agent(ea.agent, exp, self.settings, self.chat_client))
                for ea in links
            ]
            sim = Simulator(
                market,
                agents,
                start=start,
                costs=ExecutionCosts(float(exp.commission_rate), float(exp.slippage_bps)),
                initial_cash=float(links[0].initial_cash),
            )
            provenance = regime_provenance(self.settings)
            regimes = regime_labels(market, self.settings)

            if exp.checkpoint is None:
                exp.config = {**exp.config, **provenance}
                state = sim.initial_state()
                for ea in links:
                    self._snapshot(session, ea, state, market.days[start])
                self._checkpoint(exp, state, market)
            else:
                # The Simulator keeps the original `start` (agents see `t - start`); only
                # `t` and the books come from the checkpoint.
                state = SimState.from_json(json.dumps(exp.checkpoint))
                recorded = {k: exp.config.get(k) for k in provenance}
                if recorded != provenance:
                    raise RuntimeError(
                        f"regime model changed since the run started: {recorded} -> {provenance}"
                    )
            exp.status = ExperimentStatus.RUNNING
            session.commit()
            log.info("experiment_running", experiment_id=str(exp.id), day=state.t)

            days = 0
            while state.t < len(market) - 1:
                if max_days is not None and days >= max_days:
                    return
                t = state.t
                before = {ea.agent.slug: len(state.books[ea.agent.slug].fills) for ea in links}
                state = sim.step(state)
                for ea, agent in zip(links, agents, strict=True):
                    self._record_day(session, ea, agent, state, market, t, before, regimes[t])
                self._checkpoint(exp, state, market)
                session.commit()  # the day's rows and the checkpoint, atomically
                days += 1

            exp.status = ExperimentStatus.COMPLETED
            session.commit()
            log.info("experiment_completed", experiment_id=str(exp.id))

    @staticmethod
    def _checkpoint(exp: Experiment, state: SimState, market: MarketData) -> None:
        exp.checkpoint = cast(dict[str, Any], json.loads(state.to_json()))
        exp.last_checkpoint_day = market.days[state.t]

    @staticmethod
    def _snapshot(session: Session, ea: ExperimentAgent, state: SimState, day: date) -> None:
        book = state.books[ea.agent.slug]
        session.add(
            PortfolioSnapshot(
                experiment_agent_id=ea.id,
                day=day,
                equity=_money(book.equity[-1]),
                cash=_money(book.portfolio.cash),
                holdings={str(a): q for a, q in book.portfolio.holdings.items()},
            )
        )

    def _record_day(
        self,
        session: Session,
        ea: ExperimentAgent,
        agent: RecordingAgent,
        state: SimState,
        market: MarketData,
        t: int,
        fills_before: Mapping[str, int],
        regime: Regime,
    ) -> None:
        rec = agent.last
        assert rec is not None  # noqa: S101 (step() asked every agent)
        d = rec.decision
        weights = d.weights() if d is not None else rec.weights
        decision = DecisionRow(
            id=uuid.uuid4(),
            experiment_agent_id=ea.id,
            day=market.days[t],
            target_weights={str(a): w for a, w in weights.items()},
            confidence=None if d is None else Decimal(str(round(d.confidence, 3))),
            rationale=None if d is None else d.rationale,
            regime=regime,
            attempts=rec.attempts,
            held_position=d is None,
            latency_ms=rec.latency_ms,
        )
        session.add(decision)
        book = state.books[ea.agent.slug]
        for f in book.fills[fills_before[ea.agent.slug] :]:
            session.add(
                TradeRow(
                    decision_id=decision.id,
                    asset=str(f.asset),
                    side=TradeSide(str(f.side)),
                    quantity=Decimal(repr(f.quantity)),
                    price=Decimal(repr(f.price)),
                    fee=Decimal(repr(f.fee)),
                    executed_at=_midnight(f.day),
                )
            )
        self._snapshot(session, ea, state, market.days[t + 1])
