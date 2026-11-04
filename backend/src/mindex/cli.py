"""Command line entry point: `uv run mindex fetch-data | baseline | bench-llm`."""

import argparse
import json
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict
from pathlib import Path

from mindex.agents.base import BaseAgent
from mindex.agents.llm import (
    LlamaCppClient,
    LLMAgent,
    anonymise,
    build_messages,
    deanonymise,
    decision_schema,
)
from mindex.agents.rule import BuyAndHoldAgent, EqualWeightAgent, MovingAverageCrossAgent
from mindex.config import get_settings
from mindex.data import sources
from mindex.data.snapshot import build_frame, load_window, write_snapshot
from mindex.data.splits import FULL_RANGE, SPLITS, SealedTestSetError, Split
from mindex.domain.decision import Asset, parse_decision
from mindex.evaluation.budget import ComputeBudget, LatencySummary
from mindex.evaluation.report import check_targets, herd, summarise, to_markdown
from mindex.logging_config import configure_logging
from mindex.sim.engine import Observation, Portfolio, Simulator
from mindex.sim.market import MarketData, MarketView

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SNAPSHOT = REPO_ROOT / "data" / "snapshots"
DEFAULT_REPORTS = REPO_ROOT / "reports"
LOOKBACK_DAYS = 31  # 30 daily returns need 31 closes


def fetch_data(out: Path) -> None:
    end = min(FULL_RANGE.end, sources.last_closed_day())
    spot, futures = sources.CcxtSpot(), sources.CcxtFutures()
    candles = {a: sources.fetch_daily_candles(spot, a, FULL_RANGE.start, end) for a in Asset}
    funding = {a: sources.fetch_daily_funding(futures, a, FULL_RANGE.start, end) for a in Asset}
    df = build_frame(candles, sources.fetch_fear_greed(), funding)
    manifest = write_snapshot(
        df, out, source="binance spot 1d + binanceusdm funding + alternative.me"
    )
    print(json.dumps(manifest, indent=2))


def _market(snapshot: Path, split: Split, unseal: bool) -> tuple[MarketData, int]:
    df = load_window(snapshot, split, lookback_days=LOOKBACK_DAYS, unseal=unseal)
    market = MarketData.from_frame(df)
    start = next(i for i, d in enumerate(market.days) if d >= SPLITS[split].start)
    return market, start


def _llm_client() -> LlamaCppClient:
    s = get_settings()
    return LlamaCppClient(s.llm_base_url, s.llm_model, timeout=s.llm_timeout_seconds)


def baseline(snapshot: Path, reports: Path, split: Split, *, with_llm: bool, unseal: bool) -> None:
    market, start = _market(snapshot, split, unseal)
    agents: list[BaseAgent] = [BuyAndHoldAgent(), EqualWeightAgent(), MovingAverageCrossAgent()]
    if with_llm:
        agents.append(LLMAgent(_llm_client(), max_retries=get_settings().llm_max_retries))
    state = Simulator(market, agents, start=start).run()
    summaries = [summarise(a.agent_id, str(a.kind), state.books[a.agent_id]) for a in agents]
    herd_corr = herd(state.books, [a.agent_id for a in agents])

    bench_file = reports / "llm-benchmark.json"
    latency = None
    if bench_file.exists():
        latency = LatencySummary(**json.loads(bench_file.read_text(encoding="utf-8"))["latency"])
    checks = check_targets(summaries, latency)

    reports.mkdir(parents=True, exist_ok=True)
    period = (market.days[start], market.days[-1])
    md = to_markdown(f"Baseline sonuçları · {split}", period, summaries, herd_corr, checks)
    _write(reports / f"baseline-{split}.md", md)
    _write_json(
        reports / f"baseline-{split}.json",
        {
            "split": str(split),
            "period": [d.isoformat() for d in period],
            "agents": [asdict(s) for s in summaries],
            "herd_correlation": herd_corr,
            "targets": [asdict(c) for c in checks],
        },
    )
    print(md)


def _write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")  # LF on Windows too (.gitattributes)


def _write_json(path: Path, data: object) -> None:
    _write(path, json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def bench_llm(snapshot: Path, reports: Path, calls: int) -> None:
    """Time real decision calls on validation-period observations (llama-server must be up)."""
    market, start = _market(snapshot, Split.VALIDATION, unseal=False)
    client = _llm_client()
    codes = anonymise(market.assets)
    schema = decision_schema(list(codes.values()))
    seconds: list[float] = []
    invalid = 0
    for i in range(calls):
        t = start + i % (len(market) - start - 1)
        obs = Observation(MarketView(market, t), t - start, Portfolio(10_000.0), {}, 10_000.0)
        began = time.perf_counter()
        raw = client.complete(build_messages(obs, "momentum", codes), schema=schema)
        seconds.append(time.perf_counter() - began)
        try:
            parse_decision(deanonymise(raw, codes))
        except ValueError:
            invalid += 1
    latency = LatencySummary.of(seconds)
    budget = ComputeBudget()
    result = {
        "model": client.model,
        "calls": calls,
        "invalid_json": invalid,
        "latency": asdict(latency),
        "budget": {
            **asdict(budget),
            "llm_calls": budget.calls,
            "hours_at_p50": round(budget.hours(latency.p50_s), 1),
            "hours_at_p95": round(budget.hours(latency.p95_s), 1),
            "max_seconds_per_call_for_50h": round(budget.max_seconds_per_call(), 2),
        },
    }
    reports.mkdir(parents=True, exist_ok=True)
    _write_json(reports / "llm-benchmark.json", result)
    print(json.dumps(result, indent=2))


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="mindex", description="Mindex P3 araçları")
    parser.add_argument("--snapshot", type=Path, default=DEFAULT_SNAPSHOT)
    parser.add_argument("--reports", type=Path, default=DEFAULT_REPORTS)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("fetch-data", help="Binance + Fear & Greed verisini çekip Parquet'e yaz")
    base = sub.add_parser("baseline", help="Kural tabanlı (ve isteğe bağlı LLM) baseline koşusu")
    base.add_argument("--split", type=Split, default=Split.VALIDATION, choices=list(Split))
    base.add_argument("--llm", action="store_true", help="ilk LLM ajanını da koştur")
    base.add_argument("--unseal", action="store_true", help="yalnızca nihai değerlendirmede")
    bench = sub.add_parser("bench-llm", help="llama.cpp karar çağrısı hız ölçümü")
    bench.add_argument("--calls", type=int, default=30)
    args = parser.parse_args(argv)

    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page
    configure_logging(get_settings().log_level, json=False)
    try:
        if args.command == "fetch-data":
            fetch_data(args.snapshot)
        elif args.command == "baseline":
            baseline(args.snapshot, args.reports, args.split, with_llm=args.llm, unseal=args.unseal)
        else:
            bench_llm(args.snapshot, args.reports, args.calls)
    except SealedTestSetError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
