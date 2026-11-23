"""Command line entry point: `uv run mindex <command>` (see `mindex --help`)."""

import argparse
import getpass
import json
import sys
import time
import uuid
from collections.abc import Sequence
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path
from typing import Any, cast

from mindex.agents.base import BaseAgent
from mindex.agents.llm import (
    DECISION_V1,
    MEMORY_K,
    PROMPT_VERSIONS,
    LlamaCppClient,
    LLMAgent,
    LLMUnavailableError,
    RecalledLesson,
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
from mindex.rl import train as rl_train
from mindex.rl.env import TradingEnv
from mindex.rl.train import PPOHyperparams
from mindex.sim.engine import Observation, Portfolio, Simulator
from mindex.sim.market import MarketData, MarketView

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SNAPSHOT = REPO_ROOT / "data" / "snapshots"
DEFAULT_REPORTS = REPO_ROOT / "reports"
DEFAULT_MODELS = REPO_ROOT / "models"
DEFAULT_TS = REPO_ROOT / "frontend" / "src" / "api" / "generated.ts"
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


# Lessons as the model writes them (length and style), for timing the memory prompt: the
# benchmark has no database, so C1's recalled lessons are stood in for by these.
BENCH_LESSONS = (
    "ASSET_A pozisyonu %10 kaybettirdi; %5 zarar-kes kaybı %5'e indirirdi, bu yüzden aşırı "
    "oynak varlıklarda zarar-kes kullanmak gerekir.",
    "ASSET_B pozisyonu %4,2 kazandırdı; yarım boyut %2,1 getirirdi, trend güçlüyken tam "
    "boyutu tutmak doğruydu.",
    "ASSET_C pozisyonu %1,8 kaybettirdi; girmemek en iyisiydi, belirsiz rejimlerde pozisyon "
    "açmadan önce beklemek daha güvenli.",
)


def bench_llm(
    snapshot: Path,
    reports: Path,
    calls: int,
    prompt_version: str = DECISION_V1,
    lessons: int | None = None,
) -> None:
    """Time real decision calls on validation-period observations (llama-server must be up).

    `lessons` (decision-v2 only) adds that many sample lessons to every prompt, the C1 context;
    `None` is C0. Anything but the default (`decision-v1`, no lessons) is written to its own
    file, so the benchmark `baseline` reads stays the C0 baseline's.
    """
    market, start = _market(snapshot, Split.VALIDATION, unseal=False)
    client = _llm_client()
    codes = anonymise(market.assets)
    schema = decision_schema(list(codes.values()))
    seconds: list[float] = []
    invalid = 0
    for i in range(calls):
        t = start + i % (len(market) - start - 1)
        obs = Observation(MarketView(market, t), t - start, Portfolio(10_000.0), {}, 10_000.0, 3)
        recalled = None
        if lessons is not None:
            recalled = [
                RecalledLesson(
                    uuid.UUID(int=k),
                    BENCH_LESSONS[k % len(BENCH_LESSONS)],
                    0.9 - 0.1 * k,
                    obs.view.day - timedelta(days=3 + 7 * k),
                    "bear",
                )
                for k in range(lessons)
            ]
        messages = build_messages(
            obs, "momentum", codes, prompt_version=prompt_version, lessons=recalled
        )
        began = time.perf_counter()
        raw = client.complete(messages, schema=schema)
        seconds.append(time.perf_counter() - began)
        try:
            parse_decision(deanonymise(raw, codes))
        except ValueError:
            invalid += 1
    latency = LatencySummary.of(seconds)
    budget = ComputeBudget()
    result = {
        "model": client.model,
        "prompt_version": prompt_version,
        "lessons": lessons,
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
    default = prompt_version == DECISION_V1 and lessons is None
    name = (
        "llm-benchmark.json"
        if default
        else f"llm-benchmark-{prompt_version}-lessons{lessons or 0}.json"
    )
    _write_json(reports / name, result)
    print(json.dumps(result, indent=2))


def train_ppo(snapshot: Path, out: Path, seed: int, hp: PPOHyperparams) -> None:
    """Train on the train split, select on validation. The test split is never loaded here."""
    train_market, train_start = _market(snapshot, Split.TRAIN, unseal=False)
    val_market, val_start = _market(snapshot, Split.VALIDATION, unseal=False)
    train_env = TradingEnv(
        train_market,
        start=train_start,
        turnover_penalty=hp.turnover_penalty,
        episode_length=hp.episode_length,
    )
    val_env = TradingEnv(val_market, start=val_start)  # no penalty: report the net log return
    periods = {
        "train": (train_market.days[train_start], train_market.days[-1]),
        "validation": (val_market.days[val_start], val_market.days[-1]),
    }
    manifest = rl_train.train_ppo(
        train_env, val_env, hp, seed=seed, out_dir=out / f"seed-{seed}", periods=periods
    )
    print(json.dumps({k: manifest[k] for k in ("seed", "best", "files")}, indent=2))


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


def export_openapi(ts: Path | None, json_out: Path | None) -> None:
    """Write the API schema as TypeScript declarations (and optionally as JSON); no server."""
    from mindex.api.app import create_app
    from mindex.api.typescript import declarations

    schema = create_app().openapi()
    if json_out is not None:
        _write_json(json_out, schema)
    if ts is not None:
        _write(ts, declarations(schema))
        print(f"{ts} yazıldı")


def serve_api(host: str, port: int, *, reload: bool) -> None:
    import uvicorn  # imported lazily: the data and baseline commands do not need a server

    uvicorn.run(
        "mindex.api.app:create_server_app", factory=True, host=host, port=port, reload=reload
    )


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


# ---------------------------------------------------------------- studies (#54)

STUDY_AGENTS = (
    "buy-hold-btc",
    "equal-weight",
    "llm-momentum",
    "llm-mean-reversion",
    "llm-sentiment",
    "llm-risk-averse",
)


def _study_error(exc: Exception) -> SystemExit:
    """An API refusal (422 with fields) as a readable CLI error."""
    from fastapi import HTTPException

    if isinstance(exc, HTTPException):
        detail = exc.detail
        if isinstance(detail, dict):
            body = cast(dict[str, Any], detail)
            fields = cast(dict[str, str], body.get("fields") or {})
            lines = [str(body.get("detail", ""))] + [f"  {k}: {v}" for k, v in fields.items()]
            return SystemExit("\n".join(lines))
        return SystemExit(str(detail))
    return SystemExit(str(exc))


def study_create(args: argparse.Namespace) -> None:
    """Every condition x seed as draft experiments; `--smoke`: 14 days, the first seed."""
    from fastapi import HTTPException
    from pydantic import ValidationError
    from sqlalchemy import select

    from mindex.api.schemas import StudyCreate
    from mindex.db.models import User, UserRole
    from mindex.db.session import get_sessionmaker
    from mindex.services.study import create_study, study_out

    try:
        body = StudyCreate(
            name=args.name,
            start_date=args.start,
            end_date=args.end,
            assets=args.assets,
            agent_ids=args.agents,
            seeds=list(range(1, args.seeds + 1)),
            smoke=args.smoke,
        )
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(map(str, e['loc']))}: {e['msg']}"
            for e in exc.errors(include_input=False, include_url=False)
        )
        raise SystemExit(f"Geçersiz çalışma: {problems}") from None
    settings = get_settings()
    with get_sessionmaker()() as session:
        owner = session.scalar(select(User).where(User.email == args.owner))
        if owner is None or owner.role is not UserRole.RESEARCHER:
            raise SystemExit(f"{args.owner}: araştırmacı kullanıcı yok (mindex create-user)")
        try:
            study = create_study(session, settings, owner.id, body)
        except HTTPException as exc:
            raise _study_error(exc) from None
        out = study_out(session, study)
    period = f"{out.start_date} / {out.end_date}"
    print(f"Çalışma {out.id}: {len(out.runs)} deney ({period}, seed {out.seeds})")
    print(f"Başlatmak için: mindex study start {out.id}")


def study_start(study_id: str, *, run: bool) -> None:
    """Queue the study's draft or failed runs and, unless `run` is False, run them here one by
    one (a stopped command resumes: run it again)."""
    from fastapi import HTTPException

    from mindex.db.session import get_sessionmaker
    from mindex.services.runner import ExperimentRunner
    from mindex.services.study import get_study, queue_study, study_out

    settings = get_settings()
    sessions = get_sessionmaker()
    with sessions() as session:
        study = get_study(session, study_id)
        if study is None:
            raise SystemExit(f"Çalışma bulunamadı: {study_id}")
        try:
            queued = queue_study(session, settings, study)
        except HTTPException as exc:
            raise _study_error(exc) from None
        runs = {r.experiment_id: r for r in study_out(session, study).runs}
    print(f"{len(queued)} deney kuyrukta")
    if not run:
        print("API sunucusu (mindex serve) kuyruğu açılışta devralır.")
        return
    runner = ExperimentRunner(sessions, settings)
    for i, experiment_id in enumerate(queued, 1):
        r = runs[str(experiment_id)]
        print(f"[{i}/{len(queued)}] {r.condition} seed {r.seed} koşuyor...", flush=True)
        started = time.perf_counter()
        runner(experiment_id)
        print(f"  bitti ({time.perf_counter() - started:.0f} sn)")
    study_status(study_id)


def study_status(study_id: str) -> None:
    from mindex.db.session import get_sessionmaker
    from mindex.services.study import compare, get_study, study_out

    with get_sessionmaker()() as session:
        study = get_study(session, study_id)
        if study is None:
            raise SystemExit(f"Çalışma bulunamadı: {study_id}")
        out = study_out(session, study)
        result = compare(session, study)
    print(f"{out.name} [{out.status}] {out.start_date} / {out.end_date}, seed {out.seeds}")
    for r in out.runs:
        print(f"  {r.condition:<13} seed {r.seed:<3} {r.status:<10} son gün {r.last_day or '-'}")
    if result is None:
        print("Henüz tamamlanan koşu yok.")
        return
    kind = "tam" if result.complete else "kısmi"
    print(
        f"\nKarşılaştırma ({kind}; {result.days} gün, blok {result.block_length}, "
        f"{result.resamples} yeniden örnekleme)"
    )
    print("koşul          koşu  Sharpe  %95 GA             MDD     getiri  sürü   ders")
    for c in result.conditions:
        lesson = "-" if c.lesson_consistency is None else f"{c.lesson_consistency:.0%}"
        print(
            f"{c.condition:<13} {c.runs:>5} {c.sharpe_mean:>7.2f}  "
            f"[{c.sharpe_ci_low:>6.2f}, {c.sharpe_ci_high:>6.2f}]  {c.max_drawdown:>6.1%} "
            f"{c.total_return:>7.1%} {c.herd_correlation:>5.2f}  {lesson}"
        )
    for d in result.differences:
        print(
            f"{d.condition} - {d.baseline}: fark Sharpe {d.sharpe_diff:+.2f} "
            f"[{d.ci_low:+.2f}, {d.ci_high:+.2f}]"
        )


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
    bench.add_argument("--prompt", choices=PROMPT_VERSIONS, default=DECISION_V1)
    bench.add_argument(
        "--lessons",
        type=int,
        choices=range(MEMORY_K + 1),
        help="decision-v2: bu kadar örnek dersi prompt'a ekle (C1 bağlamı)",
    )
    defaults = PPOHyperparams()
    ppo = sub.add_parser("train-ppo", help="PPO eğitimi (train), doğrulamada model seçimi")
    ppo.add_argument("--seed", type=int, default=0)
    ppo.add_argument("--out", type=Path, default=DEFAULT_MODELS / "ppo", help="artefakt kök dizini")
    ppo.add_argument("--timesteps", type=int, default=defaults.total_timesteps)
    ppo.add_argument("--eval-every", type=int, default=defaults.eval_every)
    ppo.add_argument("--turnover-penalty", type=float, default=defaults.turnover_penalty)
    hmm = sub.add_parser("train-hmm", help="Rejim HMM'ini yalnızca eğitim döneminde eğit")
    hmm.add_argument("--out", type=Path, default=DEFAULT_MODELS / "regime-hmm.json")
    hmm.add_argument("--seed", type=int, default=0)
    user = sub.add_parser("create-user", help="Kullanıcı oluştur (parola istemle/stdin'den)")
    user.add_argument("--email", required=True)
    user.add_argument("--role", choices=["researcher", "viewer"], default="viewer")
    spec = sub.add_parser("openapi", help="OpenAPI şemasını TypeScript tiplerine dök")
    spec.add_argument("--ts", type=Path, default=DEFAULT_TS, help="generated.ts yolu")
    spec.add_argument("--json", type=Path, default=None, help="isteğe bağlı openapi.json yolu")
    validation = SPLITS[Split.VALIDATION]
    study = sub.add_parser("study", help="C0-C3 x seed çalışması (#54)")
    study_sub = study.add_subparsers(dest="study_command", required=True)
    create = study_sub.add_parser("create", help="Her koşul x seed için taslak deney oluştur")
    create.add_argument("--owner", required=True, help="araştırmacının e-postası")
    create.add_argument("--name", default="C0-C3 karşılaştırması")
    create.add_argument("--start", default=validation.start.isoformat())
    create.add_argument("--end", default=validation.end.isoformat())
    create.add_argument("--assets", nargs="+", default=[str(a) for a in Asset])
    create.add_argument("--agents", nargs="+", default=list(STUDY_AGENTS))
    create.add_argument("--seeds", type=int, default=5, help="1..N seed")
    create.add_argument("--smoke", action="store_true", help="14 gün, tek seed: hızlı deneme")
    begin = study_sub.add_parser("start", help="Kuyruğa al ve burada sırayla koştur")
    begin.add_argument("study_id")
    begin.add_argument("--no-run", action="store_true", help="yalnızca kuyruğa al (API koşar)")
    status = study_sub.add_parser("status", help="Koşuların durumu ve karşılaştırma tablosu")
    status.add_argument("study_id")
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
        elif args.command == "train-ppo":
            hp = PPOHyperparams(
                total_timesteps=args.timesteps,
                eval_every=args.eval_every,
                turnover_penalty=args.turnover_penalty,
            )
            train_ppo(args.snapshot, args.out, args.seed, hp)
        elif args.command == "create-user":
            create_user(args.email, args.role)
        elif args.command == "openapi":
            export_openapi(args.ts, args.json)
        elif args.command == "study":
            if args.study_command == "create":
                study_create(args)
            elif args.study_command == "start":
                study_start(args.study_id, run=not args.no_run)
            else:
                study_status(args.study_id)
        elif args.command == "serve":
            serve_api(args.host, args.port, reload=args.reload)
        else:
            bench_llm(args.snapshot, args.reports, args.calls, args.prompt, args.lessons)
    except SealedTestSetError as exc:
        parser.error(str(exc))
    except LLMUnavailableError as exc:
        raise SystemExit(
            f"LLM sunucusuna ulaşılamadı ({get_settings().llm_base_url}): {exc}. "
            "llama-server'ın çalıştığını ve MINDEX_LLM_BASE_URL'i denetleyin."
        ) from None


if __name__ == "__main__":
    main()
