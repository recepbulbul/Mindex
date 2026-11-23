"""Studies (#54): every condition x seed created and queued together, run, and compared."""

# Fixtures are imported from test_runner, so parameters of the same name redefine them.
# ruff: noqa: F811

import uuid
from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

import mindex.services.runner
import mindex.services.study
from mindex import cli
from mindex.config import Settings
from mindex.db.models import (
    DecisionForumRead,
    DecisionRow,
    Experiment,
    ExperimentAgent,
    ExperimentStatus,
    Study,
    User,
    UserRole,
)
from mindex.evaluation.bootstrap import bootstrap_sharpe
from mindex.memory.embedder import HashEmbedder
from mindex.services.runner import ExperimentRunner, lesson_consistency
from mindex.services.study import CONDITIONS
from test_forum_runner import ForumChat
from test_runner import (  # fixtures and helpers shared with the runner tests
    PASSWORD,
    START,
    DownChat,
    ListQueue,
    _login,  # pyright: ignore[reportPrivateUsage]
    api,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    jobs,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    researcher,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    sessions,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    settings,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    snapshot,  # noqa: F401  # pyright: ignore[reportUnusedImport]
    viewer,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)

pytestmark = pytest.mark.db

AGENTS = ["buy-hold-btc", "llm-momentum", "llm-risk-averse"]
STUDY: dict[str, Any] = {
    "name": "Koşul karşılaştırması",
    "startDate": START.isoformat(),
    "endDate": "2025-11-20",
    "assets": ["BTC", "ETH"],
    "agentIds": AGENTS,
    "seeds": [1, 2],
    "smoke": False,
    "commissionRate": 0.001,
    "slippageBps": 5,
}


def _create(api: TestClient, headers: dict[str, str], **over: Any) -> dict[str, Any]:
    res = api.post("/api/studies", json={**STUDY, **over}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def fake_runner(sessions: Callable[[], Session], settings: Settings) -> ExperimentRunner:
    """Seed-sensitive fake model: runs of different seeds give different results, so a
    comparison that mixed seeds would show."""
    return ExperimentRunner(
        sessions, settings, lambda exp: ForumChat(seed=exp.seed), HashEmbedder()
    )


# ------------------------------------------------------------------ create and start


def test_create_makes_every_condition_for_every_seed(
    api: TestClient, researcher: dict[str, str], db_session: Session
) -> None:
    study = _create(api, researcher)
    runs = study["runs"]
    assert [(r["seed"], r["condition"]) for r in runs] == [
        (seed, str(c)) for seed in (1, 2) for c in CONDITIONS
    ]
    assert {r["status"] for r in runs} == {"draft"}
    assert study["status"] == "draft"
    assert (study["startDate"], study["endDate"], study["smoke"]) == (
        "2025-10-01",
        "2025-11-20",
        False,
    )
    exps = db_session.scalars(
        select(Experiment).where(Experiment.study_id == uuid.UUID(study["id"]))
    ).all()
    assert len(exps) == 10
    assert {e.prompt_version for e in exps} == {"decision-v4"}
    assert {(e.start_date, e.end_date) for e in exps} == {(START, date(2025, 11, 20))}
    one = api.get(f"/api/experiments/{runs[0]['experimentId']}", headers=researcher).json()
    assert one["studyId"] == study["id"]
    assert one["name"] == "Koşul karşılaştırması · C0 · seed 1"
    assert api.get(f"/api/studies/{study['id']}", headers=researcher).json() == study
    assert [s["id"] for s in api.get("/api/studies", headers=researcher).json()] == [study["id"]]


def test_smoke_is_a_short_window_and_one_seed(api: TestClient, researcher: dict[str, str]) -> None:
    study = _create(api, researcher, smoke=True, seeds=[3, 4, 5])
    assert study["seeds"] == [3]
    assert study["endDate"] == (START + timedelta(days=14)).isoformat()
    assert len(study["runs"]) == len(CONDITIONS)


@pytest.mark.parametrize(
    ("over", "field", "text"),
    [
        ({"startDate": "2026-03-20", "endDate": "2026-04-10"}, "endDate", "test"),
        ({"startDate": "2026-05-01", "endDate": "2026-06-01"}, "startDate", "test"),
        ({"agentIds": ["buy-hold-btc", "equal-weight"]}, "agentIds", "LLM ajanı"),
        ({"agentIds": ["mcp-guest", "llm-momentum"]}, "agentIds", "MCP"),
        ({"seeds": []}, "seeds", "seed"),
        ({"seeds": [1, 1]}, "seeds", "farklı"),
        ({"endDate": "2025-09-01"}, "endDate", "Bitiş"),
    ],
)
def test_create_refuses(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    over: dict[str, Any],
    field: str,
    text: str,
) -> None:
    res = api.post("/api/studies", json={**STUDY, **over}, headers=researcher)
    assert res.status_code == 422, res.text
    assert text in res.json()["fields"][field]
    assert db_session.scalar(select(Study)) is None  # all or nothing
    assert db_session.scalar(select(Experiment)) is None


def test_viewers_read_but_do_not_create(api: TestClient, viewer: dict[str, str]) -> None:
    assert api.post("/api/studies", json=STUDY, headers=viewer).status_code == 403
    assert api.get("/api/studies", headers=viewer).json() == []
    assert api.get(f"/api/studies/{uuid.uuid4()}", headers=viewer).status_code == 404
    assert api.get("/api/studies/not-a-uuid", headers=viewer).status_code == 404
    assert api.get("/api/studies").status_code == 401


def test_start_queues_seed_by_seed_and_only_for_the_owner(
    api: TestClient,
    researcher: dict[str, str],
    db_session: Session,
    jobs: ListQueue,
) -> None:
    study = _create(api, researcher)
    other = _login(api, db_session, "baska@mindex.dev", UserRole.RESEARCHER)
    assert api.post(f"/api/studies/{study['id']}/start", headers=other).status_code == 403
    started = api.post(f"/api/studies/{study['id']}/start", headers=researcher)
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "queued"
    assert [str(j) for j in jobs.jobs] == [r["experimentId"] for r in study["runs"]]
    # Starting again submits the runs still queued once more (after a killed process they
    # would never run otherwise); the runner's lock and status check make a repeat harmless.
    again = api.post(f"/api/studies/{study['id']}/start", headers=researcher)
    assert again.status_code == 200
    assert jobs.jobs[10:] == jobs.jobs[:10]


# ------------------------------------------------------------------ comparison


@pytest.fixture
def finished_study(
    api: TestClient,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
    jobs: ListQueue,
    db_session: Session,
) -> dict[str, Any]:
    study = _create(api, researcher, smoke=True)
    res = api.get(f"/api/studies/{study['id']}/comparison", headers=researcher)
    assert res.status_code == 409  # nothing completed yet
    api.post(f"/api/studies/{study['id']}/start", headers=researcher)
    runner = fake_runner(sessions, settings)
    for experiment_id in jobs.jobs:
        runner(experiment_id)
    db_session.expire_all()  # the API shares this session; the runner wrote through others
    return api.get(f"/api/studies/{study['id']}", headers=researcher).json()


def test_comparison_of_a_finished_study(
    api: TestClient, viewer: dict[str, str], finished_study: dict[str, Any], db_session: Session
) -> None:
    assert finished_study["status"] == "completed"
    res = api.get(f"/api/studies/{finished_study['id']}/comparison", headers=viewer)
    assert res.status_code == 200, res.text
    comp = res.json()
    assert comp["complete"] is True
    assert (comp["days"], comp["blockLength"], comp["resamples"]) == (14, 2, 2000)
    rows = {c["condition"]: c for c in comp["conditions"]}
    assert list(rows) == [str(c) for c in CONDITIONS]
    for c in rows.values():
        assert c["runs"] == 1
        assert c["sharpeCiLow"] <= c["sharpeMean"] <= c["sharpeCiHigh"]
        assert 0 <= c["maxDrawdown"] < 1
        assert -1 <= c["herdCorrelation"] <= 1
    assert rows["C0"]["lessonConsistency"] is None
    # The rate the runs recorded (post-mortems counted before rejection).
    with_lessons = 0
    for condition in ("C1", "C1_NO_REGIME", "C2", "C3"):
        exp = db_session.get(Experiment, uuid.UUID(_run(finished_study, condition)))
        assert exp is not None
        valid, consistent = lesson_consistency(exp.config)
        expected = None if valid == 0 else pytest.approx(consistent / valid)
        assert rows[condition]["lessonConsistency"] == expected
        with_lessons += valid > 0
    assert with_lessons, "positions closed and post-mortems ran in the memory conditions"
    pairs = [(d["condition"], d["baseline"]) for d in comp["differences"]]
    assert pairs == [
        ("C1", "C0"),
        ("C1", "C1_NO_REGIME"),
        ("C2", "C1"),
        ("C3", "C2"),
        ("C3", "C0"),
    ]
    c3_c0 = comp["differences"][-1]
    assert c3_c0["sharpeDiff"] == pytest.approx(rows["C3"]["sharpeMean"] - rows["C0"]["sharpeMean"])
    assert c3_c0["ciLow"] <= c3_c0["sharpeDiff"] <= c3_c0["ciHigh"]
    # Deterministic: asked again, the same numbers.
    again = api.get(f"/api/studies/{finished_study['id']}/comparison", headers=viewer).json()
    assert again == comp
    # Each experiment's report carries the study's table (#14).
    report = api.get(f"/api/experiments/{_run(finished_study, 'C3')}/report", headers=viewer)
    assert report.json()["conditions"] == comp["conditions"]


def _run(study: dict[str, Any], condition: str) -> str:
    return next(r["experimentId"] for r in study["runs"] if r["condition"] == condition)


def test_partial_comparison_uses_completed_runs_only(
    api: TestClient,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
    jobs: ListQueue,
    db_session: Session,
) -> None:
    study = _create(api, researcher, smoke=True)
    api.post(f"/api/studies/{study['id']}/start", headers=researcher)
    runner = fake_runner(sessions, settings)
    runner(jobs.jobs[0])  # C0 only
    runner.run(jobs.jobs[4], max_days=3)  # C3 stopped half-way: not completed
    db_session.expire_all()
    res = api.get(f"/api/studies/{study['id']}/comparison", headers=researcher)
    assert res.status_code == 200, res.text
    comp = res.json()
    assert comp["complete"] is False
    assert [c["condition"] for c in comp["conditions"]] == ["C0"]
    assert comp["differences"] == []
    assert api.get(f"/api/studies/{study['id']}", headers=researcher).json()["status"] == "running"


# ------------------------------------------------------------------ CLI


@pytest.fixture
def cli_env(db_session: Session, settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Session:
    factory = sessionmaker(
        bind=db_session.connection(),
        join_transaction_mode="create_savepoint",
        expire_on_commit=False,
    )
    monkeypatch.setattr("mindex.db.session.get_sessionmaker", lambda: factory)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    def runner(s: Callable[[], Session], _: Settings) -> ExperimentRunner:
        return fake_runner(s, settings)

    monkeypatch.setattr(mindex.services.runner, "ExperimentRunner", runner)
    db_session.add(User(email="hoca@mindex.dev", password_hash=PASSWORD, role=UserRole.RESEARCHER))
    db_session.commit()
    return db_session


def test_cli_smoke_study_end_to_end(cli_env: Session, capsys: pytest.CaptureFixture[str]) -> None:
    cli.main(
        [
            "study",
            "create",
            "--owner",
            "hoca@mindex.dev",
            "--smoke",
            "--start",
            "2025-10-01",
            "--assets",
            "BTC",
            "ETH",
            "--agents",
            *AGENTS,
        ]
    )
    out = capsys.readouterr().out
    assert "5 deney" in out
    study = cli_env.scalar(select(Study))
    assert study is not None
    cli.main(["study", "start", str(study.id)])
    out = capsys.readouterr().out
    assert "5 deney kuyrukta" in out
    assert "[5/5]" in out
    assert "Karşılaştırma (tam; 14 gün" in out
    assert "C3 - C0" in out
    cli_env.expire_all()
    statuses = cli_env.scalars(select(Experiment.status).where(Experiment.study_id == study.id))
    assert set(statuses) == {ExperimentStatus.COMPLETED}
    cli.main(["study", "status", str(study.id)])
    assert "[completed]" in capsys.readouterr().out


def test_cli_refuses_the_test_window_and_unknown_owners(cli_env: Session) -> None:
    with pytest.raises(SystemExit, match="test seti"):
        cli.main(
            [
                "study",
                "create",
                "--owner",
                "hoca@mindex.dev",
                "--start",
                "2026-04-01",
                "--end",
                "2026-05-01",
            ]
        )
    with pytest.raises(SystemExit, match="araştırmacı kullanıcı yok"):
        cli.main(["study", "create", "--owner", "yok@mindex.dev", "--smoke"])
    with pytest.raises(SystemExit, match="Geçersiz çalışma"):
        cli.main(["study", "create", "--owner", "hoca@mindex.dev", "--seeds", "0"])
    with pytest.raises(SystemExit, match="bulunamadı"):
        cli.main(["study", "status", str(uuid.uuid4())])
    assert cli_env.scalar(select(Study)) is None


def test_study_runs_are_not_edited_or_deleted_alone(
    api: TestClient, researcher: dict[str, str]
) -> None:
    study = _create(api, researcher)
    run = f"/api/experiments/{study['runs'][0]['experimentId']}"
    edit = api.patch(run, json={"endDate": "2025-11-01"}, headers=researcher)
    assert edit.status_code == 409
    assert "çalışmaya ait" in edit.json()["detail"]
    assert api.delete(run, headers=researcher).status_code == 409


def test_a_run_that_left_the_study_period_is_refused_not_truncated(
    api: TestClient,
    researcher: dict[str, str],
    finished_study: dict[str, Any],
    db_session: Session,
) -> None:
    exp = db_session.get(Experiment, uuid.UUID(_run(finished_study, "C2")))
    assert exp is not None
    exp.end_date = date(2025, 10, 12)  # as if edited behind the study's back
    db_session.commit()
    res = api.get(f"/api/studies/{finished_study['id']}/comparison", headers=researcher)
    assert res.status_code == 409
    assert "çalışmanınkinden farklı" in res.json()["detail"]


def test_cli_start_stops_at_a_failed_run(
    cli_env: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def down(s: Callable[[], Session], _: Settings) -> ExperimentRunner:
        chat = DownChat(down_from_day=3)
        return ExperimentRunner(s, settings, lambda exp: chat, HashEmbedder())

    monkeypatch.setattr(mindex.services.runner, "ExperimentRunner", down)
    create = ["study", "create", "--owner", "hoca@mindex.dev", "--smoke"]
    cli.main([*create, "--assets", "BTC", "ETH", "--agents", *AGENTS])
    study = cli_env.scalar(select(Study))
    assert study is not None
    with pytest.raises(SystemExit, match="failed: LLMUnavailableError"):
        cli.main(["study", "start", str(study.id)])
    out = capsys.readouterr().out
    assert "[1/5]" in out
    assert "[2/5]" not in out  # it stopped at the first failure


# ------------------------------------------------------------------ review of #58 (Fable)


def _llm_sharpe(api: TestClient, headers: dict[str, str], experiment_id: str) -> float:
    agents = api.get(f"/api/experiments/{experiment_id}/report", headers=headers).json()["agents"]
    llm = [a["sharpe"] for a in agents if a["agentId"].startswith("llm-")]
    return sum(llm) / len(llm)


def test_differences_pair_only_the_seeds_both_conditions_completed(
    api: TestClient,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
    jobs: ListQueue,
    db_session: Session,
) -> None:
    """A partial study: C0 has seeds 1 and 2, C3 only seed 1. C3 - C0 must compare seed 1
    with seed 1, not C3's one seed with C0's two."""
    end = (START + timedelta(days=14)).isoformat()
    study = _create(api, researcher, seeds=[1, 2], endDate=end)
    api.post(f"/api/studies/{study['id']}/start", headers=researcher)
    runner = fake_runner(sessions, settings)
    c0_s1, c3_s1, c0_s2 = jobs.jobs[0], jobs.jobs[4], jobs.jobs[5]
    for job in (c0_s1, c3_s1, c0_s2):
        runner(job)
    db_session.expire_all()
    comp = api.get(f"/api/studies/{study['id']}/comparison", headers=researcher).json()
    assert comp["complete"] is False
    rows = {c["condition"]: c for c in comp["conditions"]}
    assert (rows["C0"]["runs"], rows["C0"]["complete"]) == (2, True)
    assert (rows["C3"]["runs"], rows["C3"]["complete"]) == (1, False)
    # Only pairs with a common completed seed; C1, C1', C2 have none.
    assert [(d["condition"], d["baseline"], d["seeds"]) for d in comp["differences"]] == [
        ("C3", "C0", 1)
    ]
    # Not vacuous: the two C0 seeds differ, so mixing them would change the difference.
    c0_one, c0_two = (_llm_sharpe(api, researcher, str(j)) for j in (c0_s1, c0_s2))
    assert abs(c0_one - c0_two) > 0.05
    paired = _llm_sharpe(api, researcher, str(c3_s1)) - c0_one
    assert comp["differences"][0]["sharpeDiff"] == pytest.approx(paired)
    # The report carries the same per-condition completeness.
    report = api.get(f"/api/experiments/{c0_s1}/report", headers=researcher).json()
    assert [c["complete"] for c in report["conditions"]] == [True, False]


def test_the_comparison_is_cached_until_a_run_changes(
    api: TestClient,
    researcher: dict[str, str],
    finished_study: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    real = bootstrap_sharpe

    def counting(*args: Any, **kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(mindex.services.study, "bootstrap_sharpe", counting)
    url = f"/api/studies/{finished_study['id']}/comparison"
    first = api.get(url, headers=researcher).json()
    after_first = calls
    assert api.get(url, headers=researcher).json() == first
    report = f"/api/experiments/{_run(finished_study, 'C0')}/report"
    assert api.get(report, headers=researcher).json()["conditions"] == first["conditions"]
    assert calls == after_first  # served from the cache, not resampled again


def test_report_of_a_mismatched_study_is_409_not_500(
    api: TestClient,
    researcher: dict[str, str],
    finished_study: dict[str, Any],
    db_session: Session,
) -> None:
    exp = db_session.get(Experiment, uuid.UUID(_run(finished_study, "C2")))
    assert exp is not None
    exp.end_date = date(2025, 10, 12)
    db_session.commit()
    res = api.get(f"/api/experiments/{_run(finished_study, 'C0')}/report", headers=researcher)
    assert res.status_code == 409
    assert "çalışmanınkinden farklı" in res.json()["detail"]


def test_cli_start_again_resumes_the_runs_a_failure_left_queued(
    cli_env: Session,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """'The same command resumes': after a failure, a second `study start` runs the failed
    run from its checkpoint and every run the first one left queued."""

    def down(s: Callable[[], Session], _: Settings) -> ExperimentRunner:
        chat = DownChat(down_from_day=3)
        return ExperimentRunner(s, settings, lambda exp: chat, HashEmbedder())

    def working(s: Callable[[], Session], _: Settings) -> ExperimentRunner:
        return fake_runner(s, settings)

    create = ["study", "create", "--owner", "hoca@mindex.dev", "--smoke"]
    cli.main([*create, "--assets", "BTC", "ETH", "--agents", *AGENTS])
    study = cli_env.scalar(select(Study))
    assert study is not None
    monkeypatch.setattr(mindex.services.runner, "ExperimentRunner", down)
    with pytest.raises(SystemExit, match="failed"):
        cli.main(["study", "start", str(study.id)])
    capsys.readouterr()
    monkeypatch.setattr(mindex.services.runner, "ExperimentRunner", working)
    cli.main(["study", "start", str(study.id)])
    assert "5 deney kuyrukta" in capsys.readouterr().out
    cli_env.expire_all()
    statuses = cli_env.scalars(select(Experiment.status).where(Experiment.study_id == study.id))
    assert set(statuses) == {ExperimentStatus.COMPLETED}


def test_mean_forum_weight_per_condition(
    api: TestClient, viewer: dict[str, str], finished_study: dict[str, Any], db_session: Session
) -> None:
    """C3 - C2 mixes two things: telling senders apart and the forum's overall weight. The
    mean weight the agents read with shows the second (C2: always 1/2)."""
    comp = api.get(f"/api/studies/{finished_study['id']}/comparison", headers=viewer).json()
    rows = {c["condition"]: c for c in comp["conditions"]}
    for c in ("C0", "C1", "C1_NO_REGIME"):
        assert rows[c]["meanForumWeight"] is None  # no forum
    assert rows["C2"]["meanForumWeight"] == 0.5
    c3 = uuid.UUID(_run(finished_study, "C3"))
    weights = db_session.scalars(
        select(DecisionForumRead.weight)
        .join(DecisionRow, DecisionRow.id == DecisionForumRead.decision_id)
        .join(ExperimentAgent, ExperimentAgent.id == DecisionRow.experiment_agent_id)
        .where(ExperimentAgent.experiment_id == c3)
    ).all()
    assert weights
    assert rows["C3"]["meanForumWeight"] == pytest.approx(
        float(sum(weights)) / len(weights), abs=1e-6
    )


def test_herd_correlation_is_null_below_two_llm_agents(
    api: TestClient,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
    jobs: ListQueue,
    db_session: Session,
) -> None:
    study = _create(api, researcher, smoke=True, agentIds=["buy-hold-btc", "llm-momentum"])
    api.post(f"/api/studies/{study['id']}/start", headers=researcher)
    runner = fake_runner(sessions, settings)
    for job in jobs.jobs:
        runner(job)
    db_session.expire_all()
    comp = api.get(f"/api/studies/{study['id']}/comparison", headers=researcher).json()
    assert {c["herdCorrelation"] for c in comp["conditions"]} == {None}  # not 0: "no herding"


def test_queueing_claims_in_sql_and_never_requeues_a_run_finished_meanwhile(
    api: TestClient,
    researcher: dict[str, str],
    sessions: Callable[[], Session],
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Between listing a study's runs and queueing them, another worker may finish one. The
    claim is a conditional UPDATE, so that run stays completed and is not handed out again."""
    study = _create(api, researcher, smoke=True)
    first = uuid.UUID(study["runs"][0]["experimentId"])
    mine = sessions()
    row = mine.get(Study, uuid.UUID(study["id"]))
    assert row is not None
    stale = mindex.services.study.study_runs(mine, row)  # all five drafts, as listed
    other = sessions()
    done = other.get(Experiment, first)
    assert done is not None
    done.status = ExperimentStatus.COMPLETED  # finished by someone else meanwhile
    other.commit()

    def listed(*_: object) -> list[Experiment]:
        return stale

    monkeypatch.setattr(mindex.services.study, "study_runs", listed)
    queued = mindex.services.study.queue_study(mine, settings, row)
    assert first not in queued
    assert len(queued) == 4
    check = sessions()
    status = check.get(Experiment, first)
    assert status is not None
    assert status.status is ExperimentStatus.COMPLETED
