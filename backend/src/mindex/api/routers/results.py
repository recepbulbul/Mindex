"""Read endpoints of a started experiment: timeline, agent detail, report, memories, forum.

Shapes follow `frontend/src/api/types.ts`. Equity, decisions and trades come from the rows the
runner commits each day; report metrics come from the simulator checkpoint (full float
precision, the numbers `mindex baseline` reports). The forum endpoint returns the posts, the
current trust counts and the trust history replayed from the verdict days (`verified_on`); it
is empty outside C2/C3. The report's `conditions` is the study's condition comparison for an
experiment in a study. Regimes are the labels the run stored; a run without a regime
model is marked `regime_source: "placeholder"` in its `config` and shows "sideways" on every
day.
"""

import json
import uuid
from collections import defaultdict
from datetime import date
from typing import Annotated, cast

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select

from mindex.agents.rule import BuyAndHoldAgent
from mindex.api.deps import CurrentUser, SessionDep, SettingsDep
from mindex.api.routers.experiments import NOT_FOUND, get_experiment_row
from mindex.api.schemas import (
    AgentDetailOut,
    AgentMetrics,
    AgentOut,
    AgentRun,
    CandleOut,
    ConditionSummary,
    CounterfactualOut,
    DecisionOut,
    EquityPoint,
    ForumMessageOut,
    ForumOut,
    MemoryOut,
    MemoryRef,
    ReportOut,
    TimelineOut,
    TradeOut,
    TrustHistoryPoint,
    TrustScoreOut,
)
from mindex.config import Settings
from mindex.data.snapshot import DataQualityError
from mindex.db.models import (
    AgentKindDb,
    AgentRow,
    DecisionForumRead,
    DecisionMemory,
    DecisionRow,
    Experiment,
    ExperimentStatus,
    ForumMessageRow,
    MemoryRow,
    PortfolioSnapshot,
    Study,
    TradeRow,
    TrustScoreRow,
)
from mindex.domain.decision import Asset
from mindex.domain.metrics import herd_correlation
from mindex.domain.regime import Regime
from mindex.domain.trust import BetaTrust
from mindex.evaluation.report import BENCHMARK_ID, differences, summarise
from mindex.memory.store import MemoryStore
from mindex.services.runner import (
    PLACEHOLDER_REGIME,
    REGIME_SOURCE,
    DataUnavailableError,
    agent_available,
    agent_rows,
    experiment_market,
    load_market,
)
from mindex.services.study import compare
from mindex.sim.engine import AgentBook, ExecutionCosts, SimState, Simulator
from mindex.sim.market import MarketData

router = APIRouter(prefix="/experiments", tags=["results"])

NOT_STARTED = "Deney henüz başlatılmadı."
NO_RESULTS = "Deney henüz sonuç üretmedi."
AGENT_NOT_IN_EXPERIMENT = "Ajan bu deneyde yok."
NO_PRICES = "Fiyat anlık görüntüsü bu deneyin dönemini kapsamıyor."
HELD_RATIONALE = "Karar yok: pozisyon korundu."


def _started(session: SessionDep, experiment_id: str, *, draft_status: int) -> Experiment:
    """The experiment, unless it is a draft: 409 for the timeline, 404 elsewhere (as the mock)."""
    exp = get_experiment_row(session, experiment_id)
    if exp.status is ExperimentStatus.DRAFT:
        detail = NOT_STARTED if draft_status == status.HTTP_409_CONFLICT else NOT_FOUND
        raise HTTPException(draft_status, detail)
    return exp


def _agent_out(a: AgentRow, settings: Settings) -> AgentOut:
    return AgentOut(
        id=a.slug,
        name=a.name,
        kind=a.kind,
        persona=a.persona,
        available=agent_available(a, settings),
    )


def _snapshots(
    session: SessionDep, ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[PortfolioSnapshot]]:
    out: dict[uuid.UUID, list[PortfolioSnapshot]] = defaultdict(list)
    rows = session.scalars(
        select(PortfolioSnapshot)
        .where(PortfolioSnapshot.experiment_agent_id.in_(ids))
        .order_by(PortfolioSnapshot.day)
    )
    for r in rows:
        out[r.experiment_agent_id].append(r)
    return out


# A missing or corrupt snapshot is a server problem (503); a sealed period is not caught
# here (SealedTestSetError), it cannot reach a started experiment through the API.
SNAPSHOT_ERRORS = (DataUnavailableError, DataQualityError, FileNotFoundError)


def _market(exp: Experiment, settings: Settings) -> MarketData:
    try:
        return experiment_market(exp, settings)[0]
    except SNAPSHOT_ERRORS:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_PRICES) from None


def _weights(s: PortfolioSnapshot, market: MarketData, i: int) -> dict[Asset, float]:
    # Valued from the snapshot's own cash and holdings (not its rounded `equity`), so the
    # weights never sum above 1.
    held = cast(dict[str, float], s.holdings)
    values = {a: held.get(str(a), 0.0) * market.bars[a][i].close for a in market.assets}
    total = float(s.cash) + sum(values.values())
    return {a: min(1.0, v / total) if total > 0 else 0.0 for a, v in values.items()}


@router.get(
    "/{experiment_id}/timeline", responses={status.HTTP_409_CONFLICT: {"description": NOT_STARTED}}
)
def timeline(
    experiment_id: str, session: SessionDep, settings: SettingsDep, _: CurrentUser
) -> TimelineOut:
    """Days up to the last checkpoint; `candles` has one key per experiment asset."""
    exp = _started(session, experiment_id, draft_status=status.HTTP_409_CONFLICT)
    links = agent_rows(exp)
    snaps = _snapshots(session, [ea.id for ea in links])
    days = [s.day for s in snaps[links[0].id]]
    if not days:  # queued, or failed before its first day: nothing to show yet
        empty = TimelineOut(
            experiment_id=str(exp.id), days=[], regimes=[], candles={}, runs=[], trades=[]
        )
        return empty
    market = _market(exp, settings)
    index = [market.index_of(d) for d in days]

    runs = [
        AgentRun(
            agent=_agent_out(ea.agent, settings),
            equity=[EquityPoint(day=s.day, equity=float(s.equity)) for s in snaps[ea.id]],
            weights=[_weights(s, market, i) for s, i in zip(snaps[ea.id], index, strict=True)],
        )
        for ea in links
    ]
    slug_of = {ea.id: ea.agent.slug for ea in links}
    trades = session.execute(
        select(TradeRow, DecisionRow.experiment_agent_id)
        .join(DecisionRow, TradeRow.decision_id == DecisionRow.id)
        .where(DecisionRow.experiment_agent_id.in_(list(slug_of)))
        .order_by(TradeRow.executed_at, DecisionRow.experiment_agent_id, TradeRow.asset)
    ).all()
    candles = {
        a: [
            CandleOut(
                time=market.days[i],
                open=market.bars[a][i].open,
                high=market.bars[a][i].high,
                low=market.bars[a][i].low,
                close=market.bars[a][i].close,
                volume=market.bars[a][i].volume,
            )
            for i in index
        ]
        for a in market.assets
    }
    return TimelineOut(
        experiment_id=str(exp.id),
        days=days,
        regimes=_regimes(session, exp, links[0].id, days),
        candles=candles,
        runs=runs,
        trades=[
            TradeOut(
                id=str(t.id),
                agent_id=slug_of[ea_id],
                day=t.executed_at.date(),
                asset=Asset(t.asset),
                side=t.side,
                quantity=float(t.quantity),
                price=float(t.price),
                fee=float(t.fee),
            )
            for t, ea_id in trades
        ],
    )


def _regimes(
    session: SessionDep, exp: Experiment, ea_id: uuid.UUID, days: list[date]
) -> list[Regime]:
    """The labels the run decided with (stored per decision day), never recomputed, so a
    changed model cannot rewrite history. The last marked day has no decision yet and
    carries the previous label. Placeholder runs (`regime_source`) are "sideways"."""
    if exp.config.get(REGIME_SOURCE, "placeholder") == "placeholder":
        return [PLACEHOLDER_REGIME] * len(days)
    rows = session.execute(
        select(DecisionRow.day, DecisionRow.regime).where(DecisionRow.experiment_agent_id == ea_id)
    ).all()
    stored = {day: regime for day, regime in rows}
    out: list[Regime] = []
    for d in days:
        out.append(stored.get(d) or (out[-1] if out else PLACEHOLDER_REGIME))
    return out


def _decision_out(
    r: DecisionRow, agent_id: str, refs: list[MemoryRef], forum_ids: list[str]
) -> DecisionOut:
    # Held days have no confidence or rationale in the database; the contract wants values.
    return DecisionOut(
        id=str(r.id),
        agent_id=agent_id,
        day=r.day,
        target_weights={Asset(a): float(w) for a, w in r.target_weights.items()},
        confidence=0.0 if r.confidence is None else float(r.confidence),
        rationale=r.rationale or HELD_RATIONALE,
        regime=r.regime or PLACEHOLDER_REGIME,
        attempts=r.attempts,
        held_position=r.held_position,
        latency_ms=r.latency_ms or 0,
        memories=refs,
        forum_message_ids=forum_ids,
    )


@router.get("/{experiment_id}/agents/{agent_id}")
def agent_detail(
    experiment_id: str, agent_id: str, session: SessionDep, settings: SettingsDep, _: CurrentUser
) -> AgentDetailOut:
    """One agent's equity and decisions (newest first), with the trust it gives and receives
    on the forum (C2/C3; empty in other conditions)."""
    exp = _started(session, experiment_id, draft_status=status.HTTP_404_NOT_FOUND)
    ea = next((x for x in exp.agents if x.agent.slug == agent_id), None)
    if ea is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, AGENT_NOT_IN_EXPERIMENT)
    rows = list(
        session.scalars(
            select(DecisionRow)
            .where(DecisionRow.experiment_agent_id == ea.id)
            .order_by(DecisionRow.day.desc())
        )
    )
    refs: dict[uuid.UUID, list[MemoryRef]] = defaultdict(list)
    for link in session.scalars(
        select(DecisionMemory)
        .where(DecisionMemory.decision_id.in_([r.id for r in rows]))
        .order_by(DecisionMemory.score.desc())
    ):
        refs[link.decision_id].append(MemoryRef(id=str(link.memory_id), score=float(link.score)))
    reads: dict[uuid.UUID, list[str]] = defaultdict(list)
    for decision_id, message_id in session.execute(
        select(DecisionForumRead.decision_id, DecisionForumRead.forum_message_id)
        .where(DecisionForumRead.decision_id.in_([r.id for r in rows]))
        .order_by(DecisionForumRead.weight.desc(), DecisionForumRead.forum_message_id)
    ):
        reads[decision_id].append(str(message_id))
    trust = _trust(session, exp)
    return AgentDetailOut(
        agent=_agent_out(ea.agent, settings),
        equity=[
            EquityPoint(day=s.day, equity=float(s.equity))
            for s in _snapshots(session, [ea.id])[ea.id]
        ],
        decisions=[_decision_out(r, agent_id, refs[r.id], reads[r.id]) for r in rows],
        trust_given=[t for t in trust if t.truster_id == agent_id],
        trust_received=[t for t in trust if t.trustee_id == agent_id],
    )


def _slugs(exp: Experiment) -> dict[uuid.UUID, str]:
    return {ea.id: ea.agent.slug for ea in exp.agents}


def _trust(session: SessionDep, exp: Experiment) -> list[TrustScoreOut]:
    slug_of = _slugs(exp)
    rows = session.scalars(select(TrustScoreRow).where(TrustScoreRow.truster_id.in_(list(slug_of))))
    out = [
        TrustScoreOut(
            truster_id=slug_of[r.truster_id],
            trustee_id=slug_of[r.trustee_id],
            confirmed=r.confirmed,
            refuted=r.refuted,
            score=BetaTrust(r.confirmed, r.refuted).score,
        )
        for r in rows
    ]
    return sorted(out, key=lambda t: (t.truster_id, t.trustee_id))


def _metrics(agent_id: str, kind: str, book: AgentBook) -> AgentMetrics:
    s = summarise(agent_id, kind, book)
    return AgentMetrics(
        agent_id=agent_id,
        total_return=s.total_return,
        sharpe=s.sharpe,
        max_drawdown=s.max_drawdown,
        trades=s.trades,
    )


def _benchmark(exp: Experiment, settings: Settings, state: SimState) -> AgentMetrics:
    """BTC buy-and-hold over the same days and costs; simulated when not in the experiment."""
    if BENCHMARK_ID in state.books:
        return _metrics(BENCHMARK_ID, "rule", state.books[BENCHMARK_ID])
    if all(len(b.equity) < 2 for b in state.books.values()):  # no day has been marked yet
        return AgentMetrics(
            agent_id=BENCHMARK_ID, total_return=0.0, sharpe=0.0, max_drawdown=0.0, trades=0
        )
    last_day = _market(exp, settings).days[state.t]
    try:
        btc, start = load_market(settings.snapshot_dir, exp.start_date, last_day, ["BTC"])
    except SNAPSHOT_ERRORS:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, NO_PRICES) from None
    sim = Simulator(
        btc,
        [BuyAndHoldAgent()],
        start=start,
        costs=ExecutionCosts(float(exp.commission_rate), float(exp.slippage_bps)),
    )
    return _metrics(BENCHMARK_ID, "rule", sim.run().books[BENCHMARK_ID])


@router.get(
    "/{experiment_id}/report", responses={status.HTTP_409_CONFLICT: {"description": NO_RESULTS}}
)
def report(
    experiment_id: str, session: SessionDep, settings: SettingsDep, _: CurrentUser
) -> ReportOut:
    exp = _started(session, experiment_id, draft_status=status.HTTP_404_NOT_FOUND)
    if exp.checkpoint is None:
        raise HTTPException(status.HTTP_409_CONFLICT, NO_RESULTS)
    state = SimState.from_json(json.dumps(exp.checkpoint))
    links = agent_rows(exp)
    agents = [
        _metrics(ea.agent.slug, str(ea.agent.kind), state.books[ea.agent.slug]) for ea in links
    ]
    # Like the frontend's `llmHerd`: LLM agents' daily change in invested weight; 0 below two.
    llm = [
        differences(state.books[ea.agent.slug].invested)
        for ea in links
        if ea.agent.kind is AgentKindDb.LLM
    ]
    herd = herd_correlation(llm) if len(llm) >= 2 and len(llm[0]) >= 2 else 0.0
    return ReportOut(
        experiment_id=str(exp.id),
        agents=agents,
        benchmark=_benchmark(exp, settings, state),
        herd_correlation=herd,
        conditions=_study_conditions(session, exp),
    )


def _study_conditions(session: SessionDep, exp: Experiment) -> list[ConditionSummary]:
    """The study's condition table for one of its experiments; [] outside a study or before
    any of its runs completed."""
    if exp.study_id is None:
        return []
    study = session.get(Study, exp.study_id)
    result = None if study is None else compare(session, study)
    return [] if result is None else result.conditions


@router.get("/{experiment_id}/memories")
def memories(
    experiment_id: str,
    session: SessionDep,
    _: CurrentUser,
    regime: Annotated[Regime | None, Query()] = None,
    agent: Annotated[str | None, Query(max_length=100)] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
) -> list[MemoryOut]:
    """Lessons of the experiment's agents, filtered by regime, agent slug and text."""
    exp = _started(session, experiment_id, draft_status=status.HTTP_404_NOT_FOUND)
    slug_of = {ea.id: ea.agent.slug for ea in exp.agents if not agent or ea.agent.slug == agent}
    rows = MemoryStore(session).browse(list(slug_of), regime=regime, contains=q)
    return [_memory_out(m, slug_of[m.experiment_agent_id]) for m in rows]


def _memory_out(m: MemoryRow, agent_id: str) -> MemoryOut:
    cf = cast(dict[str, float], m.counterfactual)
    return MemoryOut(
        id=str(m.id),
        agent_id=agent_id,
        day=m.day,
        lesson=m.lesson,
        counterfactual=CounterfactualOut(
            actual=cf["actual"], skip=cf["skip"], half=cf["half"], stop_loss=cf["stop_loss"]
        ),
        regime=m.regime,
        importance=float(m.importance),
    )


@router.get("/{experiment_id}/forum")
def forum(experiment_id: str, session: SessionDep, _: CurrentUser) -> ForumOut:
    """Posts (newest first), the current trust matrix and its history (C2/C3)."""
    exp = _started(session, experiment_id, draft_status=status.HTTP_404_NOT_FOUND)
    slug_of = _slugs(exp)
    rows = list(
        session.scalars(select(ForumMessageRow).where(ForumMessageRow.experiment_id == exp.id))
    )
    rows.sort(key=lambda m: (m.day, slug_of[m.sender_id], m.asset or ""), reverse=True)
    regimes = {
        (ea_id, day): regime
        for ea_id, day, regime in session.execute(
            select(DecisionRow.experiment_agent_id, DecisionRow.day, DecisionRow.regime).where(
                DecisionRow.experiment_agent_id.in_(list(slug_of))
            )
        )
    }
    messages = [
        ForumMessageOut(
            id=str(m.id),
            sender_id=slug_of[m.sender_id],
            day=m.day,
            content=m.content,
            asset=Asset(m.asset),
            stance=m.stance,
            regime=regimes.get((m.sender_id, m.day)) or PLACEHOLDER_REGIME,
            flagged=m.flagged,
            verified=m.verified,
        )
        for m in rows
        if m.asset is not None
    ]
    trust = _trust(session, exp)
    return ForumOut(
        messages=messages,
        trust=trust,
        trust_history=_trust_history(session, exp, slug_of, trust),
    )


def _trust_history(
    session: SessionDep,
    exp: Experiment,
    slug_of: dict[uuid.UUID, str],
    trust: list[TrustScoreOut],
) -> list[TrustHistoryPoint]:
    """Mean trust the other forum members place in each member, replayed from the verdicts:
    one point per member at the start and on every verdict day."""
    members = sorted({t.truster_id for t in trust})
    if not members:
        return []
    verdicts = session.execute(
        select(
            ForumMessageRow.id,
            ForumMessageRow.verified_on,
            ForumMessageRow.sender_id,
            ForumMessageRow.verified,
            DecisionRow.experiment_agent_id,
        )
        .join(DecisionForumRead, DecisionForumRead.forum_message_id == ForumMessageRow.id)
        .join(DecisionRow, DecisionRow.id == DecisionForumRead.decision_id)
        .where(ForumMessageRow.experiment_id == exp.id, ForumMessageRow.verified_on.is_not(None))
        .distinct()  # one row per (post, reader), as the runner counts
    ).all()
    by_day: dict[date, list[tuple[str, str, bool]]] = defaultdict(list)
    for _, day, sender, held, reader in verdicts:
        assert day is not None  # noqa: S101 (filtered above)
        assert held is not None  # noqa: S101
        by_day[day].append((slug_of[reader], slug_of[sender], held))
    counts = {(a, b): BetaTrust() for a in members for b in members if a != b}

    def points(day: date) -> list[TrustHistoryPoint]:
        return [
            TrustHistoryPoint(
                day=day,
                trustee_id=m,
                score=round(
                    sum(counts[(o, m)].score for o in members if o != m) / (len(members) - 1), 4
                ),
            )
            for m in members
            if len(members) > 1
        ]

    out = points(exp.start_date)
    for day in sorted(by_day):
        for reader, sender, held in by_day[day]:
            counts[(reader, sender)] = counts[(reader, sender)].update(advice_was_correct=held)
        out.extend(points(day))
    return out
