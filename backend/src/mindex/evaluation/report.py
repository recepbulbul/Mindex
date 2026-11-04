"""Summarise a simulation and compare it with the proposal's quantitative targets."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from itertools import pairwise

from mindex.domain.metrics import herd_correlation, max_drawdown, sharpe_ratio
from mindex.evaluation.budget import P95_TARGET_SECONDS, LatencySummary
from mindex.sim.engine import AgentBook

MDD_REDUCTION_TARGET = 0.30  # best LLM agent: MDD at least 30 % below BTC buy-and-hold
SHARPE_GAIN_TARGET = 0.15  # C3 vs C0 mean Sharpe of LLM agents (measured from P6 on)
BENCHMARK_ID = "buy-hold-btc"


@dataclass(frozen=True, slots=True)
class AgentSummary:
    agent_id: str
    kind: str
    total_return: float
    sharpe: float
    max_drawdown: float
    trades: int
    fees: float
    holds: int
    decisions: int


def daily_returns(equity: Sequence[float]) -> list[float]:
    return [b / a - 1 for a, b in pairwise(equity)]


def summarise(agent_id: str, kind: str, book: AgentBook) -> AgentSummary:
    eq = book.equity
    return AgentSummary(
        agent_id=agent_id,
        kind=kind,
        total_return=eq[-1] / eq[0] - 1,
        sharpe=sharpe_ratio(daily_returns(eq)),
        max_drawdown=max_drawdown(eq),
        trades=len(book.fills),
        fees=sum(f.fee for f in book.fills),
        holds=book.holds,
        decisions=book.decisions,
    )


def herd(books: Mapping[str, AgentBook], agent_ids: Sequence[str]) -> float | None:
    """Mean pairwise correlation of daily changes in invested weight; None if < 2 agents."""
    if len(agent_ids) < 2:
        return None
    changes = [differences(books[a].invested) for a in agent_ids]
    return herd_correlation(changes)


def differences(series: Sequence[float]) -> list[float]:
    return [b - a for a, b in pairwise(series)]


@dataclass(frozen=True, slots=True)
class TargetCheck:
    target: str
    measured: str
    status: str  # "karşılandı" | "karşılanmadı" | "ölçülmedi"


def check_targets(
    summaries: Sequence[AgentSummary], latency: LatencySummary | None = None
) -> list[TargetCheck]:
    by_id = {s.agent_id: s for s in summaries}
    llm = [s for s in summaries if s.kind == "llm"]
    checks = [
        TargetCheck(
            "C3 LLM ortalama Sharpe'ı C0'a göre ≥ %15 yüksek",
            "Hafıza ve forum P5-P6'da; bu koşu yalnızca C0 baseline",
            "ölçülmedi",
        )
    ]

    bench = by_id.get(BENCHMARK_ID)
    if bench is None or not llm:
        missing = "BTC al-ve-tut" if bench is None else "LLM ajanı (`--llm`)"
        checks.append(
            TargetCheck(
                "En iyi LLM ajanının MDD'si BTC al-ve-tut'tan ≥ %30 düşük",
                f"Bu koşuda {missing} yok",
                "ölçülmedi",
            )
        )
    else:
        best = min(llm, key=lambda s: s.max_drawdown)
        reduction = 1 - best.max_drawdown / bench.max_drawdown if bench.max_drawdown else 0.0
        checks.append(
            TargetCheck(
                "En iyi LLM ajanının MDD'si BTC al-ve-tut'tan ≥ %30 düşük",
                f"{best.agent_id}: MDD %{best.max_drawdown * 100:.1f} vs "
                f"%{bench.max_drawdown * 100:.1f} → %{reduction * 100:.1f} düşük",
                "karşılandı" if reduction >= MDD_REDUCTION_TARGET else "karşılanmadı",
            )
        )

    if latency is None:
        checks.append(
            TargetCheck(
                f"Karar çağrısı p95 < {P95_TARGET_SECONDS:.0f} sn",
                "llama.cpp hız ölçümü bu koşuya eklenmedi",
                "ölçülmedi",
            )
        )
    else:
        checks.append(
            TargetCheck(
                f"Karar çağrısı p95 < {P95_TARGET_SECONDS:.0f} sn",
                f"p95 {latency.p95_s:.2f} sn (n = {latency.n})",
                "karşılandı" if latency.meets_target else "karşılanmadı",
            )
        )
    return checks


def _pct(x: float) -> str:
    return f"{x * 100:+.1f} %"


def to_markdown(
    title: str,
    period: tuple[date, date],
    summaries: Sequence[AgentSummary],
    herd_corr: float | None,
    checks: Sequence[TargetCheck],
) -> str:
    lines = [
        f"# {title}",
        "",
        f"Dönem: {period[0].isoformat()} → {period[1].isoformat()} · %0,1 komisyon + 5 bp kayma, "
        "t kapanışında karar, t+1 açılışında yürütme · başlangıç 10 000 USDT",
        "",
        "| Ajan | Tür | Getiri | Sharpe | MDD | İşlem | Komisyon (USDT) | Değişiklik yok (gün) |",
        "|---|---|--:|--:|--:|--:|--:|--:|",
    ]
    for s in summaries:
        lines.append(
            f"| {s.agent_id} | {s.kind} | {_pct(s.total_return)} | {s.sharpe:.2f} | "
            f"{s.max_drawdown * 100:.1f} % | {s.trades} | {s.fees:.2f} | {s.holds}/{s.decisions} |"
        )
    lines += [
        "",
        "Sürü korelasyonu (yatırılan ağırlığın günlük değişimi, ortalama Pearson): "
        + ("—" if herd_corr is None else f"{herd_corr:.3f}"),
        "",
        "## Nicel hedeflerle karşılaştırma",
        "",
        "| Hedef (öneri formu) | Ölçülen | Durum |",
        "|---|---|---|",
        *(f"| {c.target} | {c.measured} | {c.status} |" for c in checks),
        "",
    ]
    return "\n".join(lines)
