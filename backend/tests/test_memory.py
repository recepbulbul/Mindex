"""Memory without a database: score fusion, the hash embedder and the HTTP embedding client."""

import json
import math
import uuid
from datetime import date

import httpx2
import pytest

from mindex.config import get_settings
from mindex.db.models import EMBEDDING_DIM, Regime
from mindex.memory.embedder import (
    EmbeddingUnavailableError,
    HashEmbedder,
    LlamaServerEmbedder,
)
from mindex.memory.store import REGIME_BONUS, Candidate, fuse_scores, text_query


def cand(
    distance: float,
    text_rank: float = 0.0,
    *,
    regime: Regime = Regime.BULL,
    importance: float = 0.5,
    day: date = date(2025, 1, 1),
) -> Candidate:
    return Candidate(uuid.uuid4(), day, regime, importance, distance, text_rank)


def order(scored: list[tuple[Candidate, float]]) -> list[uuid.UUID]:
    return [c.memory_id for c, _ in scored]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


# --- fuse_scores ----------------------------------------------------------


def test_fuse_empty() -> None:
    assert fuse_scores([], regime=Regime.BULL, use_regime=True) == []


def test_fuse_orders_by_vector_distance() -> None:
    near, far = cand(0.1), cand(0.6)
    assert order(fuse_scores([far, near], regime=Regime.BULL, use_regime=False)) == [
        near.memory_id,
        far.memory_id,
    ]


def test_text_match_lifts_a_lesson() -> None:
    near, matching = cand(0.10), cand(0.12, text_rank=0.05)
    scored = fuse_scores([near, matching], regime=Regime.BULL, use_regime=False)
    assert order(scored)[0] == matching.memory_id


def test_no_text_match_gets_no_text_term() -> None:
    """A lesson matching no term is not "last among text matches": it gets nothing."""
    alone = fuse_scores([cand(0.1)], regime=Regime.BULL, use_regime=False)
    assert alone[0][1] == pytest.approx(0.5 * 0.85 / (1 + REGIME_BONUS))


def test_regime_bonus_on_and_off() -> None:
    bull, bear = cand(0.2, regime=Regime.BULL), cand(0.2, regime=Regime.BEAR)
    on = dict(
        (c.memory_id, s) for c, s in fuse_scores([bull, bear], regime=Regime.BEAR, use_regime=True)
    )
    off = dict(
        (c.memory_id, s) for c, s in fuse_scores([bull, bear], regime=Regime.BEAR, use_regime=False)
    )
    assert on[bear.memory_id] == pytest.approx(on[bull.memory_id] * (1 + REGIME_BONUS))
    assert off[bear.memory_id] == pytest.approx(off[bull.memory_id])


def test_importance_breaks_equal_relevance() -> None:
    low, high = cand(0.3, importance=0.1), cand(0.3, importance=0.9)
    assert order(fuse_scores([low, high], regime=Regime.BULL, use_regime=False))[0] == (
        high.memory_id
    )


def test_importance_cannot_lift_an_irrelevant_lesson() -> None:
    relevant = cand(0.05, text_rank=0.1, importance=0.0)
    others = [cand(0.5 + i / 100) for i in range(5)]
    important = cand(0.9, importance=1.0)
    scored = fuse_scores([*others, important, relevant], regime=Regime.BULL, use_regime=True)
    assert order(scored)[0] == relevant.memory_id


def test_scores_stay_in_unit_interval() -> None:
    best = cand(0.0, text_rank=1.0, importance=1.0, regime=Regime.BULL)
    scored = fuse_scores(
        [best, cand(0.4, importance=5.0), cand(0.9, importance=-1.0)],
        regime=Regime.BULL,
        use_regime=True,
    )
    assert scored[0][1] == pytest.approx(1.0)
    assert all(0.0 < s <= 1.0 for _, s in scored)


def test_ties_break_on_newer_day_then_id() -> None:
    old, new = cand(0.2, day=date(2025, 1, 1)), cand(0.2, day=date(2025, 2, 1))
    assert order(fuse_scores([old, new], regime=Regime.BULL, use_regime=False)) == [
        new.memory_id,
        old.memory_id,
    ]
    a, b = cand(0.2), cand(0.2)
    first = order(fuse_scores([a, b], regime=Regime.BULL, use_regime=False))
    assert first == order(fuse_scores([b, a], regime=Regime.BULL, use_regime=False))


def test_text_query_ors_terms() -> None:
    assert text_query("BTC trend'i kırıldı, or -sat") == "btc or trend or i or kırıldı or sat"
    assert text_query("!!") == ""
    assert text_query("İşlem kapandı") == "işlem or kapandı"


# --- HashEmbedder -----------------------------------------------------------


def test_hash_embedder_is_deterministic_and_normalised() -> None:
    a, b = HashEmbedder().embed(["Trend kırıldı, BTC sat", "Trend kırıldı, BTC sat"])
    assert a == b
    assert len(a) == EMBEDDING_DIM
    assert math.isclose(math.sqrt(sum(x * x for x in a)), 1.0)


def test_hash_embedder_similar_text_is_closer() -> None:
    q, similar, other = HashEmbedder().embed(
        ["funding yüksekken long açma", "funding yüksekken long pozisyon riskli", "ETH yatay seyir"]
    )
    assert cosine(q, similar) > cosine(q, other)


def test_hash_embedder_empty_text_is_a_unit_vector() -> None:
    (vec,) = HashEmbedder().embed(["  ...  "])
    assert math.isclose(math.sqrt(sum(x * x for x in vec)), 1.0)


# --- LlamaServerEmbedder ------------------------------------------------------


def test_llama_server_embedder_posts_and_reorders() -> None:
    seen: list[dict[str, object]] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert str(request.url) == "http://emb:8081/v1/embeddings"
        seen.append(json.loads(request.content))
        data = [
            {"index": 1, "embedding": [2.0] * EMBEDDING_DIM},
            {"index": 0, "embedding": [1.0] * EMBEDDING_DIM},
        ]
        return httpx2.Response(200, json={"data": data})

    client = LlamaServerEmbedder(
        "http://emb:8081/v1/", "qwen3-emb", transport=httpx2.MockTransport(handler)
    )
    first, second = client.embed(["a", "b"])
    assert (first[0], second[0]) == (1.0, 2.0)
    assert seen == [{"model": "qwen3-emb", "input": ["a", "b"], "encoding_format": "float"}]
    assert client.embed([]) == []


@pytest.mark.parametrize(
    "response",
    [
        httpx2.Response(500, text="boom"),
        httpx2.Response(200, text="not json"),
        httpx2.Response(200, json={"data": []}),
        httpx2.Response(200, json={"data": [{"index": 0, "embedding": [0.1] * 8}]}),
        httpx2.Response(200, json={"data": [{"embedding": [0.1] * EMBEDDING_DIM}]}),
        httpx2.Response(200, json={"data": [{"index": 0, "embedding": None}]}),
    ],
    ids=["http-500", "bad-json", "wrong-count", "wrong-dim", "no-index", "null-embedding"],
)
def test_llama_server_embedder_errors(response: httpx2.Response) -> None:
    client = LlamaServerEmbedder(
        "http://emb/v1", "m", transport=httpx2.MockTransport(lambda _: response)
    )
    with pytest.raises(EmbeddingUnavailableError):
        client.embed(["a"])


def test_llama_server_embedder_connection_error() -> None:
    def handler(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    client = LlamaServerEmbedder("http://emb/v1", "m", transport=httpx2.MockTransport(handler))
    with pytest.raises(EmbeddingUnavailableError):
        client.embed(["a"])


def test_llama_server_embedder_rejects_non_http_url() -> None:
    with pytest.raises(ValueError, match="http"):
        LlamaServerEmbedder("file:///etc/passwd", "m")


@pytest.mark.model
def test_real_embedding_server_contract() -> None:
    """Needs a running `llama-server --embedding` with Qwen3-Embedding (`-m model`)."""
    s = get_settings()
    vectors = LlamaServerEmbedder(s.embedding_base_url, s.embedding_model).embed(
        ["BTC trendi kırıldı, pozisyon azaltıldı.", "Funding yüksekken long açmak riskli."]
    )
    assert [len(v) for v in vectors] == [EMBEDDING_DIM, EMBEDDING_DIM]
    assert all(math.isfinite(x) for v in vectors for x in v)
