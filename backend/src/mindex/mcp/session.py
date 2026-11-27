"""The arena an MCP guest plays in: one replay shared by the guests, a portfolio each.

`ArenaSession` is the only thing the MCP tools touch. It is turn-based: the day advances
when every guest of the session has placed its order for the current day, so callers drive
the clock and nothing waits on a timer. Orders execute with `Simulator.step`, i.e. exactly
like every other agent's decision: decided at the close of `t`, filled at the open of `t+1`.

It lives in memory and is not an experiment: nothing is written to the database and a
restart starts over. Taking part in a recorded experiment is the runner's job (not built
yet, see docs/02-architecture.md).
"""

from collections.abc import Sequence

from mindex.agents.base import AgentKind, BaseAgent
from mindex.domain.decision import Decision
from mindex.sim.engine import (
    DEFAULT_INITIAL_CASH,
    ExecutionCosts,
    Observation,
    Portfolio,
    Simulator,
)
from mindex.sim.market import MarketData, MarketView


class SessionFinishedError(RuntimeError):
    """The replay reached its last day: no order can execute any more."""


class GuestAgent(BaseAgent):
    """An external agent inside the simulator: it plays the order placed for it, once."""

    kind = AgentKind.EXTERNAL

    def __init__(self, agent_id: str) -> None:
        super().__init__(agent_id)
        self.pending: Decision | None = None

    def decide(self, obs: Observation) -> Decision | None:
        decision, self.pending = self.pending, None
        return decision


class ArenaSession:
    def __init__(
        self,
        market: MarketData,
        agent_ids: Sequence[str],
        *,
        start: int = 0,
        costs: ExecutionCosts | None = None,
        initial_cash: float = DEFAULT_INITIAL_CASH,
    ) -> None:
        if not agent_ids:
            raise ValueError("a session needs at least one agent")
        self._guests = {a: GuestAgent(a) for a in agent_ids}
        self._sim = Simulator(
            market, list(self._guests.values()), start=start, costs=costs, initial_cash=initial_cash
        )
        self._state = self._sim.initial_state()
        self._ordered: set[str] = set()

    @property
    def agent_ids(self) -> frozenset[str]:
        return frozenset(self._guests)

    @property
    def costs(self) -> ExecutionCosts:
        return self._sim.costs

    @property
    def view(self) -> MarketView:
        """The market up to the close of the current day; the only market access there is."""
        return MarketView(self._sim.market, self._state.t)

    @property
    def step(self) -> int:
        """Days since the session started (the anonymous day number agents see)."""
        return self._state.t - self._sim.start

    @property
    def finished(self) -> bool:
        return self._state.t >= len(self._sim.market) - 1

    @property
    def waiting_for(self) -> int:
        """Guests that have not ordered for the current day yet."""
        return len(self._guests) - len(self._ordered)

    def portfolio(self, agent_id: str) -> Portfolio:
        return self._state.books[agent_id].portfolio

    def place_order(self, agent_id: str, decision: Decision) -> bool:
        """Record `agent_id`'s order for the current day (replacing an earlier one of the same
        day). Returns True when it was the last one missing and the day advanced."""
        if self.finished:
            raise SessionFinishedError("the session has no day left to execute on")
        self._guests[agent_id].pending = decision
        self._ordered.add(agent_id)
        if self.waiting_for:
            return False
        self._state = self._sim.step(self._state)
        self._ordered.clear()
        return True
