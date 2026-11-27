import json

import pytest
from pydantic import ValidationError

from mindex.domain.decision import (
    Asset,
    Decision,
    FailureKind,
    decide_with_retries,
    parse_decision,
)

VALID = {
    "allocations": [{"asset": "BTC", "weight": 0.5}, {"asset": "ETH", "weight": 0.3}],
    "confidence": 0.7,
    "rationale": "BTC trend above 20-day MA; ETH lagging but momentum turning.",
}


def test_valid_decision_parses_and_exposes_cash() -> None:
    d = parse_decision(json.dumps(VALID))
    assert d.weights() == {Asset.BTC: 0.5, Asset.ETH: 0.3}
    assert d.cash_weight == pytest.approx(0.2)


@pytest.mark.parametrize(
    "patch",
    [
        {"allocations": [{"asset": "BTC", "weight": 0.8}, {"asset": "ETH", "weight": 0.4}]},
        {"allocations": [{"asset": "BTC", "weight": -0.1}]},
        {"allocations": [{"asset": "DOGE", "weight": 0.1}]},
        {"allocations": [{"asset": "BTC", "weight": 0.2}, {"asset": "BTC", "weight": 0.2}]},
        {"confidence": 1.5},
        {"rationale": "short"},
        {"leverage": 3},
    ],
    ids=["leverage", "short", "unknown-asset", "duplicate", "confidence", "rationale", "extra"],
)
def test_invalid_decisions_are_rejected(patch: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Decision.model_validate({**VALID, **patch})


def test_retry_succeeds_on_second_attempt() -> None:
    outputs = ["{not json", json.dumps(VALID)]
    result = decide_with_retries(lambda i: outputs[i], max_retries=2)
    assert result.decision is not None
    assert result.attempts == 2
    assert len(result.errors) == 1
    assert result.failures == (FailureKind.INVALID_JSON,)
    assert not result.held_position


def test_all_attempts_fail_holds_position() -> None:
    calls: list[int] = []

    def broken(attempt: int) -> str:
        calls.append(attempt)
        return '{"allocations": []}'

    result = decide_with_retries(broken, max_retries=2)
    assert result.held_position
    assert calls == [0, 1, 2]
    assert len(result.errors) == 3


def test_first_try_success_has_no_failures() -> None:
    assert decide_with_retries(lambda _: json.dumps(VALID)).failures == ()


def _with_allocations(*pairs: tuple[str, float]) -> str:
    return json.dumps({**VALID, "allocations": [{"asset": a, "weight": w} for a, w in pairs]})


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        ("{not json", FailureKind.INVALID_JSON),
        ("", FailureKind.INVALID_JSON),
        (json.dumps(VALID)[:-10], FailureKind.INVALID_JSON),  # cut off, e.g. by a token limit
        ("[1]", FailureKind.SCHEMA_VIOLATION),
        ('{"allocations": []}', FailureKind.SCHEMA_VIOLATION),
        (json.dumps({**VALID, "confidence": 1.5}), FailureKind.SCHEMA_VIOLATION),
        (json.dumps({**VALID, "leverage": 3}), FailureKind.SCHEMA_VIOLATION),
        (_with_allocations(("DOGE", 0.1)), FailureKind.SCHEMA_VIOLATION),
        # Rules the JSON schema sent to the model cannot express: no leverage, no duplicates.
        (_with_allocations(("BTC", 0.8), ("ETH", 0.4)), FailureKind.PORTFOLIO_VIOLATION),
        (_with_allocations(("BTC", 0.2), ("BTC", 0.2)), FailureKind.PORTFOLIO_VIOLATION),
    ],
    ids=[
        "garbage", "empty", "truncated", "not-an-object", "missing", "range", "extra",
        "unknown-asset", "leverage", "duplicate",
    ],
)  # fmt: skip
def test_each_failed_attempt_is_classified(raw: str, kind: FailureKind) -> None:
    result = decide_with_retries(lambda _: raw, max_retries=1)
    assert result.held_position
    assert result.failures == (kind, kind)


def test_failures_keep_the_order_of_the_attempts() -> None:
    outputs = ["{not json", _with_allocations(("BTC", 0.8), ("ETH", 0.4)), '{"allocations": []}']
    result = decide_with_retries(lambda i: outputs[i], max_retries=2)
    assert result.failures == (
        FailureKind.INVALID_JSON,
        FailureKind.PORTFOLIO_VIOLATION,
        FailureKind.SCHEMA_VIOLATION,
    )
