import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from conftest import synthetic_frame
from mindex import cli
from mindex.data.snapshot import write_snapshot
from mindex.data.splits import SPLITS, Split
from mindex.evaluation.budget import ComputeBudget, LatencySummary, percentile
from mindex.evaluation.report import AgentSummary, check_targets, herd, to_markdown
from mindex.sim.engine import AgentBook, Portfolio


def test_percentile_nearest_rank() -> None:
    samples = [float(i) for i in range(1, 101)]
    assert percentile(samples, 95) == 95.0
    assert percentile(samples, 0) == 1.0
    with pytest.raises(ValueError, match="no samples"):
        percentile([], 50)
    with pytest.raises(ValueError, match="q must"):
        percentile([1.0], 101)


def test_latency_summary_target() -> None:
    fast = LatencySummary.of([2.0, 3.0, 4.0])
    assert fast.meets_target
    assert not LatencySummary.of([12.0]).meets_target


def test_compute_budget_matches_proposal() -> None:
    budget = ComputeBudget()
    assert budget.days == 183
    assert budget.calls == 183 * 4 * 5 * 5
    # p95 = 10 s is roughly the 50-hour budget in the proposal's risk table
    assert budget.hours(10.0) == pytest.approx(50.8, abs=0.1)
    assert budget.max_seconds_per_call() == pytest.approx(9.84, abs=0.01)


def summary(agent_id: str, kind: str, mdd: float) -> AgentSummary:
    return AgentSummary(agent_id, kind, 0.1, 1.0, mdd, 3, 1.0, 0, 10)


def test_targets_not_measured_without_llm() -> None:
    checks = check_targets([summary("buy-hold-btc", "rule", 0.5)])
    assert [c.status for c in checks] == ["ölçülmedi"] * 3


def test_targets_with_llm_and_latency() -> None:
    rows = [summary("buy-hold-btc", "rule", 0.5), summary("llm-momentum", "llm", 0.3)]
    checks = check_targets(rows, LatencySummary.of([5.0, 6.0]))
    assert checks[1].status == "karşılandı"  # 40 % lower MDD
    assert checks[2].status == "karşılandı"
    worse = check_targets(
        [rows[0], summary("llm-momentum", "llm", 0.45)], LatencySummary.of([11.0])
    )
    assert worse[1].status == "karşılanmadı"
    assert worse[2].status == "karşılanmadı"


def test_herd_and_markdown() -> None:
    books = {
        "a": AgentBook(Portfolio(1.0), [1.0, 1.1], [0.0, 0.5, 0.2], []),
        "b": AgentBook(Portfolio(1.0), [1.0, 1.1], [0.0, 0.4, 0.1], []),
    }
    assert herd(books, ["a", "b"]) == pytest.approx(1.0)
    assert herd(books, ["a"]) is None
    md = to_markdown(
        "Başlık", (date(2026, 1, 1), date(2026, 2, 1)), [summary("x", "rule", 0.2)], None, []
    )
    assert "| x | rule |" in md
    assert "Sürü korelasyonu" in md


@pytest.fixture
def snapshot(tmp_path: Path) -> Path:
    start = SPLITS[Split.VALIDATION].start - timedelta(days=40)
    write_snapshot(synthetic_frame(start, 40 + 182), tmp_path / "snap", source="synthetic")
    return tmp_path / "snap"


def test_cli_baseline_writes_reports(snapshot: Path, tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / "llm-benchmark.json").write_text(
        json.dumps({"latency": {"n": 3, "p50_s": 4.0, "p95_s": 6.0, "max_s": 7.0}}),
        encoding="utf-8",
    )
    cli.main(["--snapshot", str(snapshot), "--reports", str(reports), "baseline"])
    result = json.loads((reports / "baseline-validation.json").read_text(encoding="utf-8"))
    assert [a["agent_id"] for a in result["agents"]] == ["buy-hold-btc", "equal-weight", "ma-cross"]
    assert result["period"][0] == SPLITS[Split.VALIDATION].start.isoformat()
    assert result["targets"][2]["status"] == "karşılandı"
    assert (reports / "baseline-validation.md").exists()


def test_cli_refuses_sealed_test_split(snapshot: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(SystemExit):
        cli.main(["--snapshot", str(snapshot), "baseline", "--split", "test"])
