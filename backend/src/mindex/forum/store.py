"""The forum of one run (C2/C3) in the database, bound to the runner's day transaction.

Every day `t` of a forum run, in one transaction with the checkpoint (NF2):

1. `verify(MarketView(market, t))`: advice whose horizon ended by day `t` gets its verdict
   (`verified`, `verified_on`), and every agent that read it updates its trust in the sender,
   once per (reader, post) however many days it read the post.
2. The agents decide; each reads through `feed(...)` the filtered posts of the previous
   `WINDOW_DAYS` days (never the same day: a post of day `t` is first read on `t + 1`, so the
   order in which agents decide cannot matter), with its own trust in each sender.
3. `record_reads` and `post` write what the decisions read and said.

Posts are screened (`domain.forum.screen`) before they are stored; flagged posts are kept for
the record but never read or judged.
"""

import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from mindex.agents.llm import Forum, ForumFeed, PostOut
from mindex.db.models import DecisionForumRead, DecisionRow, ForumMessageRow, TrustScoreRow
from mindex.domain.decision import Asset
from mindex.domain.forum import (
    HORIZON_DAYS,
    MAX_READS,
    WINDOW_DAYS,
    ForumRead,
    Stance,
    read_order,
    screen,
    verdict,
)
from mindex.domain.trust import BetaTrust
from mindex.sim.engine import Observation
from mindex.sim.market import MarketData, MarketView


class ForumStore:
    def __init__(
        self,
        session: Session,
        experiment_id: uuid.UUID,
        slugs: Mapping[uuid.UUID, str],
        market: MarketData,
        codes: Mapping[Asset, str],
    ) -> None:
        self.session = session
        self.experiment_id = experiment_id
        self.slugs = dict(slugs)  # experiment_agents.id -> agent slug, for deterministic order
        self.market = market
        self.codes = dict(codes)

    def start(self, members: Sequence[uuid.UUID]) -> None:
        """Neutral trust (a = b = 0, w = 0.5) between every pair of forum members."""
        for truster in members:
            for trustee in members:
                if truster != trustee:
                    self.session.add(TrustScoreRow(truster_id=truster, trustee_id=trustee))
        self.session.flush()

    # ------------------------------------------------------------ reading

    def trust_of(self, reader: uuid.UUID) -> dict[uuid.UUID, BetaTrust]:
        rows = self.session.scalars(select(TrustScoreRow).where(TrustScoreRow.truster_id == reader))
        return {r.trustee_id: BetaTrust(r.confirmed, r.refuted) for r in rows}

    def reads_for(self, reader: uuid.UUID, today: date) -> tuple[ForumRead, ...]:
        rows = self.session.scalars(
            select(ForumMessageRow).where(
                ForumMessageRow.experiment_id == self.experiment_id,
                ForumMessageRow.day < today,
                ForumMessageRow.day >= today - timedelta(days=WINDOW_DAYS),
                ForumMessageRow.flagged.is_(False),
                ForumMessageRow.sender_id != reader,
            )
        )
        trust = self.trust_of(reader)
        reads = [
            ForumRead(
                message_id=m.id,
                sender=self.slugs[m.sender_id],
                day=m.day,
                asset=Asset(m.asset),
                stance=m.stance,
                content=m.content,
                trust=trust.get(m.sender_id, BetaTrust()),
            )
            for m in rows
            if m.asset is not None
        ]
        return tuple(read_order(reads)[:MAX_READS])

    def feed(self, reader: uuid.UUID, *, by_trust: bool) -> Forum:
        def forum(obs: Observation) -> ForumFeed:
            return ForumFeed(self.reads_for(reader, obs.view.day), by_trust=by_trust)

        return forum

    # ------------------------------------------------------------ writing

    def record_reads(
        self, decision_id: uuid.UUID, reads: Sequence[ForumRead], weights: Sequence[float]
    ) -> None:
        for r, w in zip(reads, weights, strict=True):
            message_id = r.message_id
            assert isinstance(message_id, uuid.UUID)  # noqa: S101 (reads come from reads_for)
            self.session.add(
                DecisionForumRead(
                    decision_id=decision_id, forum_message_id=message_id, weight=_dec(w)
                )
            )

    def post(self, sender: uuid.UUID, day: date, post: PostOut) -> ForumMessageRow | None:
        """Store a screened post; None when nothing is left of it after cleaning."""
        clean = screen(post.text, self.codes)
        if clean is None:
            return None
        row = ForumMessageRow(
            id=uuid.uuid4(),
            experiment_id=self.experiment_id,
            sender_id=sender,
            day=day,
            content=clean.content,
            asset=str(post.asset),
            stance=post.stance,
            flagged=clean.flagged,
        )
        self.session.add(row)
        return row

    # ------------------------------------------------------------ verification

    def verify(self, view: MarketView) -> int:
        """Judge the advice whose horizon ended by `view.day`; returns how many were judged.

        The verdict reads closes through `view` only, so nothing after the day being run is
        used; trust changes are visible to that same day's decisions (the close of `view.day`
        is known when they are made)."""
        if view.t < HORIZON_DAYS:
            return 0
        due = self.market.days[view.t - HORIZON_DAYS]
        rows = list(
            self.session.scalars(
                select(ForumMessageRow).where(
                    ForumMessageRow.experiment_id == self.experiment_id,
                    ForumMessageRow.verified.is_(None),
                    ForumMessageRow.flagged.is_(False),
                    ForumMessageRow.stance != Stance.NEUTRAL,
                    ForumMessageRow.day <= due,
                )
            )
        )
        rows.sort(key=lambda m: (m.day, self.slugs[m.sender_id], m.asset or ""))
        judged = 0
        for m in rows:
            if m.asset is None:
                continue
            held = verdict(view, self.market.index_of(m.day), Asset(m.asset), m.stance)
            if held is None:
                continue
            m.verified, m.verified_on = held, view.day
            self._update_trust(self._readers(m.id), m.sender_id, held=held)
            judged += 1
        self.session.flush()
        return judged

    def _readers(self, message_id: uuid.UUID) -> list[uuid.UUID]:
        """Every agent that read the post, once, however many days it read it."""
        readers = self.session.scalars(
            select(DecisionRow.experiment_agent_id)
            .join(DecisionForumRead, DecisionForumRead.decision_id == DecisionRow.id)
            .where(DecisionForumRead.forum_message_id == message_id)
            .distinct()
        )
        return sorted(readers, key=lambda r: self.slugs[r])

    def _update_trust(self, readers: Iterable[uuid.UUID], sender: uuid.UUID, *, held: bool) -> None:
        for reader in readers:
            row = self.session.get(TrustScoreRow, (reader, sender))
            if row is None:  # a member the run did not start with (not expected)
                row = TrustScoreRow(truster_id=reader, trustee_id=sender, confirmed=0, refuted=0)
                self.session.add(row)
            if held:
                row.confirmed += 1
            else:
                row.refuted += 1


def _dec(x: float) -> Decimal:
    return Decimal(str(round(x, 4)))
