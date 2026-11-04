"""Rule-based benchmark agents from the proposal: BTC buy-and-hold, equal weight, MA crossover."""

from statistics import fmean

from mindex.agents.base import AgentKind, BaseAgent
from mindex.domain.decision import Allocation, Asset, Decision
from mindex.sim.engine import Observation

HELD = 0.001  # a weight above this counts as "holding" the asset


class BuyAndHoldAgent(BaseAgent):
    """Buys one asset with all cash on the first day, then never trades again."""

    kind = AgentKind.RULE

    def __init__(self, asset: Asset = Asset.BTC, agent_id: str | None = None) -> None:
        super().__init__(agent_id or f"buy-hold-{asset.lower()}")
        self.asset = asset

    def decide(self, obs: Observation) -> Decision | None:
        if obs.weights.get(self.asset, 0.0) > HELD:
            return None
        return Decision(
            allocations=[Allocation(asset=self.asset, weight=1.0)],
            confidence=1.0,
            rationale=f"Al-ve-tut: tüm nakit {self.asset} alımına gider.",
        )


class EqualWeightAgent(BaseAgent):
    """Splits equity equally across all assets and rebalances every `rebalance_days`."""

    kind = AgentKind.RULE

    def __init__(self, rebalance_days: int = 30, agent_id: str = "equal-weight") -> None:
        if rebalance_days < 1:
            raise ValueError("rebalance_days must be >= 1")
        super().__init__(agent_id)
        self.rebalance_days = rebalance_days

    def decide(self, obs: Observation) -> Decision | None:
        if obs.step % self.rebalance_days:
            return None
        assets = obs.view.assets
        return Decision(
            allocations=[Allocation(asset=a, weight=1 / len(assets)) for a in assets],
            confidence=1.0,
            rationale=f"Eşit ağırlık: {len(assets)} varlığa 1/{len(assets)} pay, "
            f"{self.rebalance_days} günde bir dengeleme.",
        )


class MovingAverageCrossAgent(BaseAgent):
    """Holds each asset whose short SMA is above its long SMA, 1/N of equity per asset."""

    kind = AgentKind.RULE

    def __init__(self, short: int = 10, long: int = 30, agent_id: str = "ma-cross") -> None:
        if not 1 <= short < long:
            raise ValueError("need 1 <= short < long")
        super().__init__(agent_id)
        self.short = short
        self.long = long

    def decide(self, obs: Observation) -> Decision | None:
        view = obs.view
        signals: list[Asset] = []
        for asset in view.assets:
            closes = view.closes(asset, self.long)
            if len(closes) < self.long:
                return None  # not enough history yet
            if fmean(closes[-self.short :]) > fmean(closes):
                signals.append(asset)
        held = {a for a, w in obs.weights.items() if w > HELD}
        if held == set(signals):
            return None  # same signal set: let weights drift instead of paying fees
        n = len(view.assets)
        return Decision(
            allocations=[Allocation(asset=a, weight=1 / n) for a in signals],
            confidence=1.0,
            rationale=(
                f"MA({self.short}) > MA({self.long}) olan varlıklar: "
                f"{', '.join(signals) or 'yok'}; geri kalanı nakitte."
            ),
        )
