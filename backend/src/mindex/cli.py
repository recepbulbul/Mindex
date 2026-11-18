"""Command line entry point: `uv run mindex <command>` (see `mindex --help`)."""

import argparse
import getpass
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
from mindex.data.snapshot import build_frame, load_split, load_window, write_snapshot
from mindex.data.splits import FULL_RANGE, SPLITS, SealedTestSetError, Split
from mindex.domain.decision import Asset, parse_decision
from mindex.evaluation.budget import ComputeBudget, LatencySummary
from mindex.evaluation.report import check_targets, herd, summarise, to_markdown
from mindex.logging_config import configure_logging
from mindex.regime.hmm import RegimeModel, regime_features
from mindex.sim.engine import Observation, Portfolio, Simulator
from mindex.sim.market import MarketData, MarketView

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SNAPSHOT = REPO_ROOT / "data" / "snapshots"
DEFAULT_REPORTS = REPO_ROOT / "reports"
DEFAULT_MODELS = REPO_ROOT / "models"
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


def train_hmm(snapshot: Path, out: Path, seed: int) -> None:
    """Fit the regime HMM on the training split only and report validation label shares."""
    model = RegimeModel.fit(
        regime_features(MarketData.from_frame(load_split(snapshot, Split.TRAIN))), seed=seed
    )
    digest = model.save(out)
    market, start = _market(snapshot, Split.VALIDATION, unseal=False)
    labels = model.label(regime_features(market))[start:]
    shares = {str(r): round(labels.count(r) / len(labels), 3) for r in sorted(set(labels))}
    print(
        json.dumps({"artifact": str(out), "sha256": digest, "validation_shares": shares}, indent=2)
    )


def serve_api(host: str, port: int, *, reload: bool) -> None:
    import uvicorn  # imported lazily: the data and baseline commands do not need a server

    uvicorn.run("mindex.api.app:create_app", factory=True, host=host, port=port, reload=reload)


def _read_password() -> str:
    if sys.stdin.isatty():
        return getpass.getpass("Parola: ")
    return sys.stdin.readline().rstrip("\r\n")  # spaces are valid password characters


def create_user(email: str, role: str, *, password: str | None = None) -> None:
    """Create a user; the only way to make a researcher (self sign-up creates viewers)."""
    from pydantic import ValidationError
    from sqlalchemy.exc import IntegrityError

    from mindex.api.schemas import RegisterRequest
    from mindex.api.security import hash_password
    from mindex.db.models import User, UserRole
    from mindex.db.session import get_sessionmaker

    if password is None:
        # Never a CLI argument: it would end up in shell history and the process list.
        password = _read_password()
    try:
        body = RegisterRequest(email=email, password=password)  # same rules as /auth/register
    except ValidationError as exc:
        # include_input=False: never echo the rejected password to the terminal or logs.
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        )
        raise SystemExit(f"Geçersiz kullanıcı: {problems}") from None
    with get_sessionmaker()() as session:
        session.add(
            User(email=body.email, password_hash=hash_password(body.password), role=UserRole(role))
        )
        try:
            session.commit()
        except IntegrityError:
            raise SystemExit(f"{body.email} zaten kayıtlı") from None
    print(f"{body.email} ({role}) oluşturuldu")


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
    hmm = sub.add_parser("train-hmm", help="Rejim HMM'ini yalnızca eğitim döneminde eğit")
    hmm.add_argument("--out", type=Path, default=DEFAULT_MODELS / "regime-hmm.json")
    hmm.add_argument("--seed", type=int, default=0)
    user = sub.add_parser("create-user", help="Kullanıcı oluştur (parola istemle/stdin'den)")
    user.add_argument("--email", required=True)
    user.add_argument("--role", choices=["researcher", "viewer"], default="viewer")
    serve = sub.add_parser("serve", help="FastAPI sunucusunu başlat (geliştirme)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--reload", action="store_true")
    args = parser.parse_args(argv)

    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if callable(reconfigure):
        reconfigure(encoding="utf-8")  # Windows consoles default to a legacy code page
    configure_logging(get_settings().log_level, json=False)
    try:
        if args.command == "fetch-data":
            fetch_data(args.snapshot)
        elif args.command == "train-hmm":
            train_hmm(args.snapshot, args.out, args.seed)
        elif args.command == "baseline":
            baseline(args.snapshot, args.reports, args.split, with_llm=args.llm, unseal=args.unseal)
        elif args.command == "create-user":
            create_user(args.email, args.role)
        elif args.command == "serve":
            serve_api(args.host, args.port, reload=args.reload)
        else:
            bench_llm(args.snapshot, args.reports, args.calls)
    except SealedTestSetError as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
