"""MemoryStore against PostgreSQL + pgvector: hybrid search, look-ahead and ownership."""

import uuid
from collections.abc import Sequence
from datetime import date

import pytest
from sqlalchemy.orm import Session

from mindex.db.models import (
    EMBEDDING_DIM,
    AgentKindDb,
    AgentRow,
    Condition,
    Experiment,
    ExperimentAgent,
    ExperimentMode,
    Regime,
    User,
)
from mindex.memory.embedder import HashEmbedder
from mindex.memory.store import MemoryStore

pytestmark = pytest.mark.db

TODAY = date(2025, 6, 10)
QUERY = "funding yüksekken long açmak riskli"


def make_agents(session: Session, n: int) -> list[uuid.UUID]:
    user = User(email=f"{uuid.uuid4().hex}@test.local", password_hash="not-a-real-hash")  # noqa: S106
    session.add(user)
    session.flush()
    exp = Experiment(
        owner_id=user.id,
        name="hafıza testi",
        mode=ExperimentMode.REPLAY,
        condition=Condition.C1,
        start_date=date(2025, 1, 1),
        assets=["BTC"],
        seed=0,
        config={},
        model_version="test",
        prompt_version="test",
    )
    session.add(exp)
    session.flush()
    ids: list[uuid.UUID] = []
    for _ in range(n):
        tag = uuid.uuid4().hex
        agent = AgentRow(slug=f"llm-{tag[:12]}", name=f"Ajan {tag}", kind=AgentKindDb.LLM)
        session.add(agent)
        session.flush()
        ea = ExperimentAgent(experiment_id=exp.id, agent_id=agent.id)
        session.add(ea)
        session.flush()
        ids.append(ea.id)
    return ids


@pytest.fixture
def store(db_session: Session) -> MemoryStore:
    return MemoryStore(db_session, HashEmbedder())


@pytest.fixture
def agent(db_session: Session) -> uuid.UUID:
    return make_agents(db_session, 1)[0]


def add(
    store: MemoryStore,
    agent: uuid.UUID,
    lesson: str,
    *,
    day: date = date(2025, 6, 1),
    regime: Regime = Regime.BULL,
    importance: float = 0.5,
) -> uuid.UUID:
    return store.add(agent, day, lesson, {"actual": 0.01}, regime, importance).id


def search(
    store: MemoryStore,
    agent: uuid.UUID,
    query: str = QUERY,
    *,
    regime: Regime = Regime.BULL,
    k: int = 5,
    use_regime: bool = True,
) -> list[uuid.UUID]:
    return [h.memory.id for h in store.search(agent, query, TODAY, regime, k, use_regime)]


def test_add_and_search(store: MemoryStore, agent: uuid.UUID) -> None:
    relevant = add(store, agent, "Funding yüksekken long açmak riskli çıktı, zarar ettim.")
    add(store, agent, "ETH yatay seyirde al-sat komisyonu eritti, bekle.")
    hits = store.search(agent, QUERY, TODAY, Regime.BULL, 5, True)
    assert hits[0].memory.id == relevant
    assert hits[0].memory.lesson.startswith("Funding")
    assert all(0 < h.score <= 1 for h in hits)
    assert hits[0].memory.lesson_tsv  # generated column is populated


def test_look_ahead_excludes_same_and_later_days(store: MemoryStore, agent: uuid.UUID) -> None:
    """A lesson identical to the query must not leak when learned today or later."""
    past = add(store, agent, "ETH yatay seyirde al-sat komisyonu eritti.", day=date(2025, 6, 9))
    add(store, agent, f"{QUERY}: aynı gün öğrenildi.", day=TODAY)
    add(store, agent, f"{QUERY}: gelecekte öğrenildi.", day=date(2025, 6, 11))
    assert search(store, agent) == [past]


def test_other_agents_memories_are_not_returned(db_session: Session, store: MemoryStore) -> None:
    mine, theirs = make_agents(db_session, 2)
    own = add(store, mine, "BTC trendi kırılınca pozisyonu yarıya indirmek işe yaradı.")
    add(store, theirs, f"{QUERY}, başka ajanın dersi.")
    assert search(store, mine) == [own]
    assert search(store, mine, k=5) == [own]


def test_regime_bonus_on_and_off(store: MemoryStore, agent: uuid.UUID) -> None:
    lesson = "Funding yüksekken long açmak riskli, pozisyonu küçült."
    bull = add(store, agent, lesson, regime=Regime.BULL)
    bear = add(store, agent, lesson, regime=Regime.BEAR)
    on = store.search(agent, QUERY, TODAY, Regime.BEAR, 5, True)
    assert [h.memory.id for h in on] == [bear, bull]
    assert on[0].score > on[1].score
    off = store.search(agent, QUERY, TODAY, Regime.BEAR, 5, False)
    assert off[0].score == pytest.approx(off[1].score)


class PinnedEmbedder:
    """Hash embeddings, except texts pinned to a given vector."""

    def __init__(self, pinned: dict[str, list[float]]) -> None:
        self.pinned = pinned
        self.fallback = HashEmbedder()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.pinned.get(t) or self.fallback.embed([t])[0] for t in texts]


def unit(i: int) -> list[float]:
    vec = [0.0] * EMBEDDING_DIM
    vec[i] = 1.0
    return vec


def test_full_text_match_changes_order(db_session: Session, agent: uuid.UUID) -> None:
    """The vector side prefers `plain`; only `keyword` contains a query word ("funding"),
    and the OR-ed tsquery matches it although the other query words are absent."""
    query = "funding sinyali nasıl okunur"
    plain_text = "Kaldıraçsız portföyde nakit oranı yüksek tutulmalı."
    keyword_text = "Funding oranı negatifken açığa satış baskısı arttı."
    no_match = "sinyal nasıl okunur"
    embedder = PinnedEmbedder(
        {query: unit(0), no_match: unit(0), plain_text: unit(0), keyword_text: unit(1)}
    )
    store = MemoryStore(db_session, embedder)
    plain = add(store, agent, plain_text)
    keyword = add(store, agent, keyword_text)
    assert search(store, agent, query, use_regime=False) == [keyword, plain]
    assert search(store, agent, no_match, use_regime=False) == [plain, keyword]


def test_k_limits_results(store: MemoryStore, agent: uuid.UUID) -> None:
    for i in range(4):
        add(store, agent, f"Ders numarası {i}: funding yüksekken temkinli ol.")
    assert len(search(store, agent, k=2)) == 2
    assert len(search(store, agent, k=10)) == 4
    with pytest.raises(ValueError, match="k"):
        search(store, agent, k=0)


def test_turkish_capital_i_matches_full_text(db_session: Session, agent: uuid.UUID) -> None:
    query, no_match = "İşlem sinyali", "sinyal nasıl"
    lesson_a = "Komisyon yüksekken sık al-sat portföyü eritti."
    lesson_b = "İşlem kapandıktan sonra zarar-kes seviyesi gözden geçirilmeli."
    embedder = PinnedEmbedder(
        {query: unit(0), no_match: unit(0), lesson_a: unit(0), lesson_b: unit(1)}
    )
    store = MemoryStore(db_session, embedder)
    a, b = add(store, agent, lesson_a), add(store, agent, lesson_b)
    assert search(store, agent, no_match, use_regime=False) == [a, b]
    assert search(store, agent, query, use_regime=False) == [b, a]


def test_query_without_words_still_searches(store: MemoryStore, agent: uuid.UUID) -> None:
    only = add(store, agent, "Funding yüksekken long açmak riskli çıktı.")
    assert search(store, agent, "!!") == [only]


def test_search_without_memories_is_empty(store: MemoryStore, agent: uuid.UUID) -> None:
    assert search(store, agent) == []
