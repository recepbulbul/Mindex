"""In-process experiment runner (F2, NF2) and the read endpoints of a run.

Prices come from a temporary Parquet snapshot built from `synthetic_frame`; the LLM agents
talk to a fake `ChatClient` whose answer depends on the prompt, so no model is needed.
"""

import json
import threading
import uuid
from collections.abc import Callable, Iterator, Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any, cast

import polars as pl
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import Engine, delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from conftest import synthetic_frame
from mindex.agents.llm import LLMUnavailableError
from mindex.api import security
from mindex.api.app import create_app, create_server_app
from mindex.api.deps import get_job_queue
from mindex.config import Settings, get_settings
from mindex.data.snapshot import write_snapshot
from mindex.data.splits import SealedTestSetError
from mindex.db.models import (
    AgentRow,
    DecisionRow,
    Experiment,
    ExperimentAgent,
    ExperimentStatus,
    PortfolioSnapshot,
    TradeRow,
    User,
    UserRole,
)
from mindex.db.session import get_session
from mindex.domain.regime import Regime
from mindex.evaluation.report import summarise
from mindex.memory.embedder import HashEmbedder
from mindex.memory.store import MemoryStore
from mindex.regime.hmm import RegimeModel, regime_features
from mindex.services.runner import (
    DataUnavailableError,
    ExperimentRunner,
    InProcessQueue,
    load_market,
    regime_labels,
    resume_interrupted,
)
from mindex.sim.engine import SimState

PASSWORD = "dogru-parola-123"
START, END = date(2025, 10, 1), date(2025, 11, 20)  # validation split, 50 decision days
CONFIG: dict[str, Any] = {
    "name": "Koşucu testi",
    "mode": "replay",
    "condition": "C0",
    "startDate": START.isoformat(),
    "endDate": END.isoformat(),
    "assets": ["BTC", "ETH"],
    "agentIds": ["equal-weight", "ma-cross", "buy-hold-btc", "llm-momentum", "llm-risk-averse"],
    "seed": 7,
    "commissionRate": 0.001,
    "slippageBps": 5,
}
pytestmark = pytest.mark.db


class Crash(BaseException):
    """A process dying mid-day: not an `Exception`, so the runner's failure handler misses it."""


class FakeChat:
    """Deterministic answers derived from the prompt (day number and asset features)."""

    def __init__(self, crash_on_day: int | None = None) -> None:
        self.crash_on_day = crash_on_day

    def complete(self, messages: list[dict[str, str]], *, schema: Mapping[str, Any]) -> str:
        user = json.loads(messages[-1]["content"])
        if user["day"] == self.crash_on_day:
            raise Crash
        allocations: list[dict[str, Any]] = []
        for code, f in sorted(user["assets"].items()):
            momentum = f["return_7d_pct"] or 0.0
            cautious = "protect capital" in messages[0]["content"]
            w = (0.2 if cautious else 0.45) if momentum > 0 else 0.05
            allocations.append({"asset": code, "weight": w})
        if user["day"] % 5 == 4:
            return "not json"  # exercises the retry path (attempts > 1)
        return json.dumps(
            {
                "allocations": allocations,
                "confidence": 0.6,
                "rationale": f"Sahte karar, gün {user['day']}.",
            }
        )


def fake_clients(crash_on_day: int | None = None) -> Callable[[Experiment], FakeChat]:
    return lambda exp: FakeChat(crash_on_day)


class DownChat(FakeChat):
    """llama-server goes away on `down_from_day`."""

    def __init__(self, down_from_day: int) -> None:
        super().__init__()
        self.down_from_day = down_from_day

    def complete(self, messages: list[dict[str, str]], *, schema: Mapping[str, Any]) -> str:
        if json.loads(messages[-1]["content"])["day"] >= self.down_from_day:
            raise LLMUnavailableError("connection refused")
        return super().complete(messages, schema=schema)


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    """Train/validation prices plus rows inside the sealed test window (must never be read)."""
    df = pl.concat(
        [synthetic_frame(date(2025, 8, 1), 130), synthetic_frame(date(2026, 3, 1), 90)]
    ).unique(["asset", "day"], keep="first")
    write_snapshot(df, tmp_path, source="synthetic")
    return tmp_path


@pytest.fixture
def settings(snapshot: Path) -> Settings:
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        jwt_secret=SecretStr("x" * 64),
        llm_model="fake-model",
        snapshot_dir=snapshot,
    )


@pytest.fixture
def sessions(db_session: Session) -> Callable[[], Session]:
    """Sessions on the test's connection: their commits are savepoints rolled back after."""
    return sessionmaker(
        bind=db_session.connection(),
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )


class ListQueue:
    def __init__(self) -> None:
        self.jobs: list[uuid.UUID] = []

    def submit(self, experiment_id: uuid.UUID) -> None:
        self.jobs.append(experiment_id)


@pytest.fixture
def jobs() -> ListQueue:
    return ListQueue()


@pytest.fixture
def api(db_session: Session, settings: Settings, jobs: ListQueue) -> Iterator[TestClient]:
    app = create_app()

    def session_override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_job_queue] = lambda: jobs
    with TestClient(app) as c:
        yield c


def _login(api: TestClient, session: Session, email: str, role: UserRole) -> dict[str, str]:
    session.add(User(email=email, password_hash=security.hash_password(PASSWORD), role=role))
    session.commit()
    res = api.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    return {"Authorization": f"Bearer {res.json()['token']}"}


@pytest.fixture
def researcher(api: TestClient, db_session: Session) -> dict[str, str]:
    return _login(api, db_session, "arastirmaci@mindex.dev", UserRole.RESEARCHER)


@pytest.fixture
def viewer(api: TestClient, db_session: Session) -> dict[str, str]:
    return _login(api, db_session, "izleyici@mindex.dev", UserRole.VIEWER)


def _started(api: TestClient, headers: dict[str, str], **over: Any) -> uuid.UUID:
    res = api.post("/api/experiments", json={**CONFIG, **over}, headers=headers)
    assert res.status_code == 201, res.text
    exp_id = res.json()["id"]
    started = api.post(f"/api/experiments/{exp_id}/start", headers=headers)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "queued"
    return uuid.UUID(exp_id)


def _status(db: Session, exp_id: uuid.UUID) -> ExperimentStatus:
    db.expire_all()
    exp = db.get(Experiment, exp_id)
    assert exp is not None
    return exp.status


def _record(db: Session, exp_id: uuid.UUID) -> dict[str, Any]:
    """Everything a run wrote, without UUIDs or wall-clock latency."""
    db.expire_all()
    exp = db.get(Experiment, exp_id)
    assert exp is not None
    slug = {ea.id: ea.agent.slug for ea in exp.agents}
    decisions = db.execute(
        select(DecisionRow).where(DecisionRow.experiment_agent_id.in_(list(slug)))
    ).scalars()
    trades = db.execute(
        select(TradeRow, DecisionRow.experiment_agent_id, DecisionRow.day)
        .join(DecisionRow, TradeRow.decision_id == DecisionRow.id)
        .where(DecisionRow.experiment_agent_id.in_(list(slug)))
    ).all()
    snaps = db.scalars(
        select(PortfolioSnapshot).where(PortfolioSnapshot.experiment_agent_id.in_(list(slug)))
    )
    return {
        "checkpoint": exp.checkpoint,
        "last_day": exp.last_checkpoint_day,
        "decisions": sorted(
            (
                slug[d.experiment_agent_id],
                d.day,
                json.dumps(d.target_weights, sort_keys=True),
                d.confidence,
                d.rationale,
                d.regime,
                d.attempts,
                d.held_position,
            )
            for d in decisions
        ),
        "trades": sorted(
            (slug[ea], day, t.asset, t.side, t.quantity, t.price, t.fee, t.executed_at)
            for t, ea, day in trades
        ),
        "snapshots": sorted(
            (slug[s.experiment_agent_id], s.day, s.equity, s.cash, json.dumps(s.holdings))
            for s in snaps
        ),
    }


# ---------------------------------------------------------------- the day loop


def test_run_writes_every_day_and_completes(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    sessions: Callable[[], Session],
    settings: Settings,
    jobs: ListQueue,
) -> None:
    exp_id = _started(api, researcher)
    assert jobs.jobs == [exp_id]
    ExperimentRunner(sessions, settings, fake_clients())(exp_id)
    assert _status(db_session, exp_id) is ExperimentStatus.COMPLETED
    rec = _record(db_session, exp_id)
    days = (END - START).days  # decision days START..END-1, marked at the next close
    assert len(rec["decisions"]) == 5 * days
    assert len(rec["snapshots"]) == 5 * (days + 1)
    assert rec["last_day"] == END
    assert rec["trades"], "rule and LLM agents trade"
    assert {d[5] for d in rec["decisions"]} == {Regime.SIDEWAYS}  # no regime model configured
    llm = [d for d in rec["decisions"] if d[0] == "llm-momentum"]
    retried = [d for d in llm if d[6] == 3]  # every attempt of day 4, 9, ... is invalid JSON
    assert retried
    assert all(d[7] for d in retried)  # ... so the agent held its position (NF2)
    state = SimState.from_json(json.dumps(rec["checkpoint"]))
    assert state.books["buy-hold-btc"].equity[-1] == pytest.approx(
        float(next(s[2] for s in rec["snapshots"] if s[0] == "buy-hold-btc" and s[1] == END)),
        abs=0.01,
    )


def test_resume_after_interruption_is_bit_for_bit(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    sessions: Callable[[], Session],
    settings: Settings,
) -> None:
    straight = _started(api, researcher)
    ExperimentRunner(sessions, settings, fake_clients())(straight)

    resumed = _started(api, researcher)
    # 1) a clean stop after 17 days (status stays "running", as when the process exits) ...
    ExperimentRunner(sessions, settings, fake_clients()).run(resumed, max_days=17)
    assert _status(db_session, resumed) is ExperimentStatus.RUNNING
    # 2) ... a crash in the middle of day 35 (after equal-weight's day-30 rebalance) ...
    with pytest.raises(Crash):
        ExperimentRunner(sessions, settings, fake_clients(crash_on_day=35))(resumed)
    partial = _record(db_session, resumed)
    assert partial["last_day"] == START + timedelta(days=35)  # day 35 rolled back as a whole
    assert len(partial["decisions"]) == 5 * 35
    # 3) ... and a fresh runner, as after a restart, finishes from the jsonb checkpoint.
    queue = ListQueue()
    assert resume_interrupted(sessions, queue) == [resumed]
    ExperimentRunner(sessions, settings, fake_clients())(queue.jobs[0])
    assert _status(db_session, resumed) is ExperimentStatus.COMPLETED
    assert _record(db_session, resumed) == _record(db_session, straight)


def test_finished_experiments_are_not_rerun(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    sessions: Callable[[], Session],
    settings: Settings,
) -> None:
    exp_id = _started(api, researcher)
    runner = ExperimentRunner(sessions, settings, fake_clients())
    runner(exp_id)
    before = _record(db_session, exp_id)
    runner(exp_id)  # e.g. submitted twice
    assert _record(db_session, exp_id) == before
    assert resume_interrupted(sessions, ListQueue()) == []


def test_failed_run_reads_cleanly(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    sessions: Callable[[], Session],
    settings: Settings,
) -> None:
    exp_id = _started(api, researcher)
    broken = settings.model_copy(update={"snapshot_dir": settings.snapshot_dir / "yok"})
    ExperimentRunner(sessions, broken, fake_clients())(exp_id)
    base = f"/api/experiments/{exp_id}"
    timeline = api.get(f"{base}/timeline", headers=researcher)
    assert timeline.status_code == 200
    assert timeline.json()["days"] == []
    assert api.get(f"{base}/report", headers=researcher).status_code == 409


def test_missing_snapshot_is_503_not_500(
    api: TestClient,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
) -> None:
    exp_id = _started(api, researcher, assets=["ETH"], agentIds=["equal-weight", "ma-cross"])
    ExperimentRunner(sessions, settings, fake_clients()).run(exp_id, max_days=3)
    for f in settings.snapshot_dir.glob("*.parquet"):
        f.unlink()
    base = f"/api/experiments/{exp_id}"
    assert api.get(f"{base}/timeline", headers=researcher).status_code == 503
    assert api.get(f"{base}/report", headers=researcher).status_code == 503


def test_report_right_after_start_has_a_zero_benchmark(
    api: TestClient,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
) -> None:
    exp_id = _started(api, researcher, assets=["ETH"], agentIds=["equal-weight", "ma-cross"])
    ExperimentRunner(sessions, settings, fake_clients()).run(exp_id, max_days=0)
    r = api.get(f"/api/experiments/{exp_id}/report", headers=researcher)
    assert r.status_code == 200
    assert r.json()["benchmark"]["totalReturn"] == 0


def test_error_marks_failed(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    sessions: Callable[[], Session],
    settings: Settings,
) -> None:
    exp_id = _started(api, researcher)
    broken = settings.model_copy(update={"snapshot_dir": settings.snapshot_dir / "yok"})
    ExperimentRunner(sessions, broken, fake_clients())(exp_id)
    assert _status(db_session, exp_id) is ExperimentStatus.FAILED
    assert _record(db_session, exp_id)["decisions"] == []


def test_sealed_test_window_is_never_read(
    db_session: Session,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
) -> None:
    # Bypass the API (which refuses this period) to prove the runner refuses it too.
    owner = db_session.scalar(select(User))
    assert owner is not None
    agents = {a.slug: a for a in db_session.scalars(select(AgentRow))}
    exp = Experiment(
        owner_id=owner.id,
        name="Mühür ihlali",
        mode="replay",
        condition="C0",
        status=ExperimentStatus.QUEUED,
        start_date=date(2026, 4, 1),
        end_date=date(2026, 5, 1),
        assets=["BTC", "ETH"],
        seed=1,
        config={**CONFIG, "agentIds": ["equal-weight", "ma-cross"]},
        model_version="fake-model",
        prompt_version="decision-v1",
    )
    exp.agents = [
        ExperimentAgent(agent=agents["equal-weight"]),
        ExperimentAgent(agent=agents["ma-cross"]),
    ]
    db_session.add(exp)
    db_session.commit()
    ExperimentRunner(sessions, settings, fake_clients())(exp.id)
    assert _status(db_session, exp.id) is ExperimentStatus.FAILED
    assert _record(db_session, exp.id)["decisions"] == []
    with pytest.raises(SealedTestSetError):
        load_market(settings.snapshot_dir, date(2026, 4, 1), date(2026, 5, 1), ["BTC"])


def test_load_market_checks_assets_and_period(settings: Settings) -> None:
    market, start = load_market(settings.snapshot_dir, START, END, ["BTC", "ETH"])
    assert market.days[start] == START
    assert market.days[-1] == END
    assert market.days[0] == START - timedelta(days=31)  # warm-up from the training split
    with pytest.raises(DataUnavailableError, match="SOL"):
        load_market(settings.snapshot_dir, START, END, ["BTC", "SOL"])
    with pytest.raises(DataUnavailableError):
        load_market(settings.snapshot_dir, date(2024, 1, 1), date(2024, 2, 1), ["BTC"])


def test_placeholder_regimes_are_marked_in_config(
    api: TestClient, viewer: dict[str, str], finished: uuid.UUID, db_session: Session
) -> None:
    exp = db_session.get(Experiment, finished)
    assert exp is not None
    assert exp.config["regime_source"] == "placeholder"
    assert exp.config["regime_sha256"] is None
    # The runner's keys do not leak into the user's configuration or its YAML.
    got = api.get(f"/api/experiments/{finished}", headers=viewer).json()
    assert got["agentIds"] == CONFIG["agentIds"]
    text = api.get(f"/api/experiments/{finished}/export.yaml", headers=viewer).text
    assert "regime" not in text


def test_hmm_regimes_are_recorded_and_pinned(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    sessions: Callable[[], Session],
    settings: Settings,
    tmp_path: Path,
) -> None:
    market, _ = load_market(settings.snapshot_dir, START, END, ["BTC", "ETH"])
    assert set(regime_labels(market, settings)) == {Regime.SIDEWAYS}
    model = RegimeModel.fit(regime_features(market), seed=0, restarts=2)
    path = tmp_path / "regime.json"
    digest = model.save(path)
    with_hmm = settings.model_copy(update={"regime_model_path": path})
    labels = model.label(regime_features(market))
    assert regime_labels(market, with_hmm) == labels

    exp_id = _started(api, researcher)
    ExperimentRunner(sessions, with_hmm, fake_clients()).run(exp_id, max_days=10)
    db_session.expire_all()
    exp = db_session.get(Experiment, exp_id)
    assert exp is not None
    assert (exp.config["regime_source"], exp.config["regime_sha256"]) == ("hmm", digest)
    t = api.get(f"/api/experiments/{exp_id}/timeline", headers=researcher).json()
    start = market.index_of(START)
    assert t["regimes"][:10] == [str(r) for r in labels[start : start + 10]]
    assert t["regimes"][10] == t["regimes"][9]  # the last marked day carries the label

    # Resuming with a different model would mix two labelings in one run: refused.
    other = tmp_path / "other.json"
    RegimeModel.fit(regime_features(market), seed=1, restarts=2).save(other)
    path.write_bytes(other.read_bytes())
    ExperimentRunner(sessions, with_hmm, fake_clients())(exp_id)
    assert _status(db_session, exp_id) is ExperimentStatus.FAILED


# ---------------------------------------------------------------- queue


def test_in_process_queue_survives_a_crashing_job() -> None:
    done: list[uuid.UUID] = []
    seen_threads: set[str] = set()

    def work(job: uuid.UUID) -> None:
        seen_threads.add(threading.current_thread().name)
        if job.int == 0:
            raise RuntimeError("boom")
        done.append(job)

    q = InProcessQueue(work)
    ok = uuid.uuid4()
    q.submit(uuid.UUID(int=0))
    q.submit(ok)
    q.join()
    q.close(timeout=5)
    assert done == [ok]
    assert seen_threads == {"mindex-runner"}


# ---------------------------------------------------------------- start endpoint


def test_start_rules(
    api: TestClient, researcher: dict[str, str], viewer: dict[str, str], jobs: ListQueue
) -> None:
    exp = api.post("/api/experiments", json=CONFIG, headers=researcher).json()
    url = f"/api/experiments/{exp['id']}/start"
    assert api.post(url).status_code == 401
    assert api.post(url, headers=viewer).status_code == 403
    assert api.post(url, headers=researcher).status_code == 200
    again = api.post(url, headers=researcher)
    assert again.status_code == 409
    assert again.json() == {"detail": '"queued" durumundaki deney başlatılamaz.'}
    assert len(jobs.jobs) == 1
    assert api.get(f"/api/experiments/{exp['id']}", headers=viewer).json()["status"] == "queued"


@pytest.mark.parametrize(
    ("over", "field"),
    [
        ({"agentIds": ["mcp-guest", "equal-weight"]}, "agentIds"),
        ({"agentIds": ["buy-hold-btc", "ma-cross"], "assets": ["ETH"]}, "agentIds"),
        ({"condition": "C3"}, "condition"),  # LLM agents run only as the C0 baseline for now
        ({"mode": "live", "startDate": "2026-10-01", "endDate": None}, "mode"),
    ],
)
def test_start_refuses_what_the_runner_cannot_run(
    api: TestClient, researcher: dict[str, str], jobs: ListQueue, over: dict[str, Any], field: str
) -> None:
    exp = api.post("/api/experiments", json={**CONFIG, **over}, headers=researcher).json()
    res = api.post(f"/api/experiments/{exp['id']}/start", headers=researcher)
    assert res.status_code == 422
    assert res.json()["detail"] == "Deney bu koşucuda başlatılamaz."
    assert field in res.json()["fields"]
    assert jobs.jobs == []
    assert api.get(f"/api/experiments/{exp['id']}", headers=researcher).json()["status"] == "draft"


def test_rule_only_experiments_run_in_any_condition(
    api: TestClient, researcher: dict[str, str]
) -> None:
    _started(api, researcher, condition="C3", agentIds=["equal-weight", "ma-cross"])


def test_unreachable_llm_fails_the_run_and_it_resumes(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    sessions: Callable[[], Session],
    settings: Settings,
    jobs: ListQueue,
) -> None:
    straight = _started(api, researcher)
    ExperimentRunner(sessions, settings, fake_clients())(straight)

    exp_id = _started(api, researcher)
    ExperimentRunner(sessions, settings, lambda exp: DownChat(down_from_day=20))(exp_id)
    assert _status(db_session, exp_id) is ExperimentStatus.FAILED
    rec = _record(db_session, exp_id)
    assert rec["last_day"] == START + timedelta(days=20)  # day 20 rolled back as a whole
    assert not any(d[7] and d[0].startswith("llm") and d[1] >= START + timedelta(days=20)
                   for d in rec["decisions"])  # fmt: skip
    got = api.get(f"/api/experiments/{exp_id}", headers=researcher).json()
    assert got["status"] == "failed"
    assert "LLMUnavailableError" in got["error"]

    # Restarting a failed run continues from its checkpoint and matches an unbroken run.
    restarted = api.post(f"/api/experiments/{exp_id}/start", headers=researcher)
    assert restarted.status_code == 200
    assert restarted.json()["error"] is None
    ExperimentRunner(sessions, settings, fake_clients())(jobs.jobs[-1])
    assert _status(db_session, exp_id) is ExperimentStatus.COMPLETED
    assert _record(db_session, exp_id) == _record(db_session, straight)


def test_trades_are_exactly_each_days_new_fills(
    api: TestClient, viewer: dict[str, str], finished: uuid.UUID, db_session: Session
) -> None:
    rec = _record(db_session, finished)
    state = SimState.from_json(json.dumps(rec["checkpoint"]))
    expected = sorted(
        (slug, f.day - timedelta(days=1), str(f.asset), f.side.value)
        for slug, book in state.books.items()
        for f in book.fills
    )
    got = sorted((t[0], t[1], t[2], t[3].value) for t in rec["trades"])
    assert got == expected


def test_start_claim_lost_to_a_concurrent_start_is_409(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    jobs: ListQueue,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exp = api.post("/api/experiments", json=CONFIG, headers=researcher).json()

    def started_meanwhile(*_: object) -> dict[str, str]:
        db_session.execute(
            update(Experiment)
            .where(Experiment.id == uuid.UUID(exp["id"]))
            .values(status=ExperimentStatus.QUEUED)
        )
        return {}

    monkeypatch.setattr("mindex.api.routers.experiments.runnable_errors", started_meanwhile)
    res = api.post(f"/api/experiments/{exp['id']}/start", headers=researcher)
    assert res.status_code == 409
    assert jobs.jobs == []


def test_start_without_a_session_is_401_even_without_a_runner(
    db_session: Session, settings: Settings
) -> None:
    app = create_app()

    def session_override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        assert c.post(f"/api/experiments/{uuid.uuid4()}/start").status_code == 401


def test_start_without_a_runner_is_503(db_session: Session, settings: Settings) -> None:
    app = create_app()

    def session_override() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_session] = session_override
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as c:
        headers = _login(c, db_session, "r@mindex.dev", UserRole.RESEARCHER)
        exp = c.post("/api/experiments", json=CONFIG, headers=headers).json()
        res = c.post(f"/api/experiments/{exp['id']}/start", headers=headers)
    assert res.status_code == 503


# ---------------------------------------------------------------- read endpoints


@pytest.fixture
def finished(
    api: TestClient,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
    db_session: Session,
) -> uuid.UUID:
    exp_id = _started(api, researcher)
    ExperimentRunner(sessions, settings, fake_clients())(exp_id)
    db_session.expire_all()
    return exp_id


def test_timeline_matches_the_contract(
    api: TestClient, viewer: dict[str, str], finished: uuid.UUID, db_session: Session
) -> None:
    res = api.get(f"/api/experiments/{finished}/timeline", headers=viewer)
    assert res.status_code == 200, res.text
    t = res.json()
    n = (END - START).days + 1
    assert t["experimentId"] == str(finished)
    assert len(t["days"]) == len(t["regimes"]) == n
    assert t["days"][0] == START.isoformat()
    assert t["days"][-1] == END.isoformat()
    assert set(t["regimes"]) == {"sideways"}
    assert set(t["candles"]) == {"BTC", "ETH"}
    assert [c["time"] for c in t["candles"]["BTC"]] == t["days"]
    assert set(t["candles"]["BTC"][0]) == {"time", "open", "high", "low", "close", "volume"}
    assert [r["agent"]["id"] for r in t["runs"]] == CONFIG["agentIds"]
    for run in t["runs"]:
        assert [p["day"] for p in run["equity"]] == t["days"]
        assert run["equity"][0]["equity"] == 10_000
        assert len(run["weights"]) == n
        assert all(sum(w.values()) <= 1 + 1e-6 for w in run["weights"])
    bh = next(r for r in t["runs"] if r["agent"]["id"] == "buy-hold-btc")
    assert bh["weights"][-1]["BTC"] > 0.99
    trade = t["trades"][0]
    assert set(trade) == {"id", "agentId", "day", "asset", "side", "quantity", "price", "fee"}
    assert {x["agentId"] for x in t["trades"]} <= set(CONFIG["agentIds"])
    assert len(t["trades"]) == len(_record(db_session, finished)["trades"])


def test_agent_detail(api: TestClient, viewer: dict[str, str], finished: uuid.UUID) -> None:
    res = api.get(f"/api/experiments/{finished}/agents/llm-momentum", headers=viewer)
    assert res.status_code == 200
    d = res.json()
    assert d["agent"]["kind"] == "llm"
    days = [x["day"] for x in d["decisions"]]
    assert days == sorted(days, reverse=True)
    first = d["decisions"][0]
    assert set(first) == {
        "id", "agentId", "day", "targetWeights", "confidence", "rationale", "regime",
        "attempts", "heldPosition", "latencyMs", "memories", "forumMessageIds",
    }  # fmt: skip
    assert d["trustGiven"] == d["trustReceived"] == []
    held = api.get(f"/api/experiments/{finished}/agents/buy-hold-btc", headers=viewer).json()
    kept = [x for x in held["decisions"] if x["heldPosition"]]
    assert kept
    assert kept[0]["rationale"] == "Karar yok: pozisyon korundu."
    assert kept[0]["confidence"] == 0
    missing = api.get(f"/api/experiments/{finished}/agents/ppo", headers=viewer)
    assert missing.status_code == 404


def test_report_uses_the_checkpoint(
    api: TestClient, viewer: dict[str, str], finished: uuid.UUID, db_session: Session
) -> None:
    r = api.get(f"/api/experiments/{finished}/report", headers=viewer).json()
    state = SimState.from_json(json.dumps(_record(db_session, finished)["checkpoint"]))
    expected = summarise("ma-cross", "rule", state.books["ma-cross"])
    ma = next(a for a in r["agents"] if a["agentId"] == "ma-cross")
    assert ma == {
        "agentId": "ma-cross",
        "totalReturn": expected.total_return,
        "sharpe": expected.sharpe,
        "maxDrawdown": expected.max_drawdown,
        "trades": expected.trades,
    }
    assert r["benchmark"] == next(a for a in r["agents"] if a["agentId"] == "buy-hold-btc")
    assert -1 <= r["herdCorrelation"] <= 1
    assert r["herdCorrelation"] != 0
    assert r["conditions"] == []


def test_report_benchmark_is_simulated_when_missing(
    api: TestClient,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
) -> None:
    exp_id = _started(api, researcher, assets=["ETH"], agentIds=["equal-weight", "ma-cross"])
    ExperimentRunner(sessions, settings, fake_clients())(exp_id)
    r = api.get(f"/api/experiments/{exp_id}/report", headers=researcher).json()
    assert r["benchmark"]["agentId"] == "buy-hold-btc"
    assert r["benchmark"]["trades"] == 1
    assert r["benchmark"]["totalReturn"] > 0  # synthetic BTC trends up
    assert r["herdCorrelation"] == 0  # fewer than two LLM agents


def test_memories_and_forum(
    api: TestClient, viewer: dict[str, str], finished: uuid.UUID, db_session: Session
) -> None:
    exp = db_session.get(Experiment, finished)
    assert exp is not None
    ea = {e.agent.slug: e for e in exp.agents}
    store = MemoryStore(db_session, HashEmbedder())
    cf = {"actual": 0.01, "skip": 0.0, "half": 0.005, "stop_loss": 0.002}
    store.add(
        ea["llm-momentum"].id,
        START,
        "Ralli sonrası %5 düşüş; boğa rejiminde kâr al.",
        cf,
        Regime.BULL,
        0.9,
    )
    store.add(
        ea["llm-risk-averse"].id,
        START,
        "Ayı rejiminde nakit tutmak düşüşü sınırladı.",
        cf,
        Regime.BEAR,
        0.4,
    )
    db_session.commit()
    url = f"/api/experiments/{finished}/memories"
    everything = api.get(url, headers=viewer).json()
    assert [m["agentId"] for m in everything] == ["llm-momentum", "llm-risk-averse"]  # importance
    assert everything[0]["counterfactual"] == {
        "actual": 0.01,
        "skip": 0.0,
        "half": 0.005,
        "stopLoss": 0.002,
    }
    assert [
        m["regime"] for m in api.get(url, params={"regime": "bear"}, headers=viewer).json()
    ] == ["bear"]
    assert len(api.get(url, params={"agent": "llm-momentum"}, headers=viewer).json()) == 1
    assert len(api.get(url, params={"q": "nakit"}, headers=viewer).json()) == 1
    assert len(api.get(url, params={"q": "%5"}, headers=viewer).json()) == 1  # % is literal
    assert api.get(url, params={"q": "%"}, headers=viewer).json()[0]["agentId"] == "llm-momentum"
    assert api.get(url, params={"q": "_"}, headers=viewer).json() == []
    assert api.get(url, params={"regime": "moon"}, headers=viewer).status_code == 422
    forum = api.get(f"/api/experiments/{finished}/forum", headers=viewer).json()
    assert forum == {"messages": [], "trust": [], "trustHistory": []}


def test_drafts_have_no_results(
    api: TestClient, researcher: dict[str, str], viewer: dict[str, str]
) -> None:
    exp = api.post("/api/experiments", json=CONFIG, headers=researcher).json()
    base = f"/api/experiments/{exp['id']}"
    assert api.get(f"{base}/timeline", headers=viewer).status_code == 409
    for path in ("/agents/llm-momentum", "/report", "/memories", "/forum"):
        assert api.get(f"{base}{path}", headers=viewer).status_code == 404
    queued = _started(api, researcher)
    assert api.get(f"/api/experiments/{queued}/report", headers=viewer).status_code == 409
    empty = api.get(f"/api/experiments/{queued}/timeline", headers=viewer).json()
    assert empty["days"] == []
    assert empty["trades"] == []


@pytest.mark.parametrize("path", ["/timeline", "/agents/x", "/report", "/memories", "/forum"])
def test_read_endpoints_need_a_session(api: TestClient, path: str) -> None:
    assert api.get(f"/api/experiments/{uuid.uuid4()}{path}").status_code == 401


def test_result_routes_are_in_openapi() -> None:
    paths = cast(
        dict[str, object], TestClient(create_app()).get("/api/openapi.json").json()["paths"]
    )
    for suffix in ("start", "timeline", "agents/{agent_id}", "report", "memories", "forum"):
        assert f"/api/experiments/{{experiment_id}}/{suffix}" in paths


def test_server_app_resumes_interrupted_runs_on_startup(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    sessions: Callable[[], Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exp_id = _started(api, researcher)
    ExperimentRunner(sessions, settings, fake_clients()).run(exp_id, max_days=5)  # "crashed"

    def runner(s: Callable[[], Session], st: Settings) -> ExperimentRunner:
        return ExperimentRunner(s, st, fake_clients())

    monkeypatch.setattr("mindex.api.app.get_sessionmaker", lambda: sessions)
    monkeypatch.setattr("mindex.api.app.get_settings", lambda: settings)
    monkeypatch.setattr("mindex.api.app.ExperimentRunner", runner)
    app = create_server_app()
    with TestClient(app):
        cast(InProcessQueue, app.state.job_queue).join()  # the real worker thread
    assert _status(db_session, exp_id) is ExperimentStatus.COMPLETED


def test_two_workers_never_run_the_same_experiment(
    db_engine: Engine, snapshot: Path, settings: Settings
) -> None:
    """Real, committed rows and two threads: the second worker must not touch a run the first
    one holds (no duplicate days, no status overwrite)."""
    with Session(db_engine) as s:
        owner = User(email="yaris@mindex.dev", password_hash="x", role=UserRole.RESEARCHER)
        s.add(owner)
        s.flush()
        agents = {a.slug: a for a in s.scalars(select(AgentRow))}
        exp = Experiment(
            owner_id=owner.id,
            name="Yarış",
            mode="replay",
            condition="C0",
            status=ExperimentStatus.QUEUED,
            start_date=START,
            end_date=START + timedelta(days=10),
            assets=["BTC", "ETH"],
            seed=1,
            config={**CONFIG, "agentIds": ["equal-weight", "llm-momentum"]},
            model_version="fake-model",
            prompt_version="decision-v1",
        )
        exp.agents = [
            ExperimentAgent(agent=agents["equal-weight"]),
            ExperimentAgent(agent=agents["llm-momentum"]),
        ]
        s.add(exp)
        s.commit()
        exp_id, owner_id = exp.id, owner.id

    first_in = threading.Event()
    second_done = threading.Event()

    class Gate(FakeChat):
        def complete(self, messages: list[dict[str, str]], *, schema: Mapping[str, Any]) -> str:
            first_in.set()
            second_done.wait(timeout=10)  # hold the run until the second worker has tried
            return super().complete(messages, schema=schema)

    factory = sessionmaker(db_engine, expire_on_commit=False)
    first = threading.Thread(
        target=ExperimentRunner(factory, settings, lambda e: Gate()), args=(exp_id,)
    )
    first.start()
    try:
        assert first_in.wait(timeout=10)
        ExperimentRunner(factory, settings, fake_clients())(exp_id)  # the second worker
        with Session(db_engine) as s:
            row = s.get(Experiment, exp_id)
            assert row is not None
            assert row.status is ExperimentStatus.RUNNING  # not overwritten
    finally:
        second_done.set()
        first.join(timeout=30)
    try:
        with Session(db_engine) as s:
            row = s.get(Experiment, exp_id)
            assert row is not None
            assert row.status is ExperimentStatus.COMPLETED
            days = s.scalars(
                select(DecisionRow.day)
                .join(ExperimentAgent, DecisionRow.experiment_agent_id == ExperimentAgent.id)
                .where(ExperimentAgent.experiment_id == exp_id)
            ).all()
            assert len(days) == 2 * 10
    finally:
        with Session(db_engine) as s:
            s.execute(delete(Experiment).where(Experiment.id == exp_id))
            s.execute(delete(User).where(User.id == owner_id))
            s.commit()


def test_only_the_owner_starts(
    api: TestClient, researcher: dict[str, str], db_session: Session, jobs: ListQueue
) -> None:
    exp = api.post("/api/experiments", json=CONFIG, headers=researcher).json()
    other = _login(api, db_session, "baska@mindex.dev", UserRole.RESEARCHER)
    res = api.post(f"/api/experiments/{exp['id']}/start", headers=other)
    assert res.status_code == 403
    assert res.json() == {
        "detail": "Bu deney başka bir araştırmacıya ait; yalnızca sahibi değiştirebilir."
    }
    assert jobs.jobs == []
