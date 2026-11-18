"""Daily Gymnasium environment over `MarketData`, with the simulator's execution semantics.

At the close of day `t` the policy sees backward-looking features (built only from a
`MarketView`, so no look-ahead) plus its current weights, and outputs target weights for the
assets and cash. Orders execute at the open of `t+1` through `sim.engine.rebalance` with the
same `ExecutionCosts` as the simulator; the reward is the log return of equity from the close of
`t` to the close of `t+1`, costs included, minus an optional turnover penalty.

`build_observation` and `action_to_weights` are shared with `PPOAgent`, so a trained policy sees
exactly the same inputs inside the arena as it did in training.
"""

import math
from collections.abc import Mapping, Sequence
from typing import Any, SupportsFloat

import gymnasium as gym
import numpy as np
from gymnasium import spaces
from numpy.typing import NDArray

from mindex.domain.decision import Asset
from mindex.sim.engine import DEFAULT_INITIAL_CASH, ExecutionCosts, Portfolio, rebalance
from mindex.sim.market import MarketData, MarketView

FEATURES_VERSION = 1  # bump whenever build_observation changes; trained models record it
WINDOW = 20  # days of history behind the features (the CLI loads 31 days of lookback)
ASSET_FEATURES = 6  # r1, r5, r20, vol20, gap to SMA20, funding rate
OBS_CLIP = 5.0
LOGIT_SCALE = 10.0  # actions in [-1, 1] → logits in [-10, 10]: the simplex corners are reachable

Obs = NDArray[np.float32]
Action = NDArray[np.float32]


def observation_size(n_assets: int) -> int:
    return n_assets * ASSET_FEATURES + 1 + n_assets + 1  # features, fear & greed, weights + cash


def _asset_features(view: MarketView, asset: Asset) -> list[float]:
    closes = view.closes(asset, WINDOW + 1)
    closes = [closes[0]] * (WINDOW + 1 - len(closes)) + closes  # short history: flat padding
    logs = np.log(np.asarray(closes, dtype=np.float64))
    rets = np.diff(logs)
    funding = view.funding_rate(asset)
    return [
        10.0 * float(rets[-1]),
        5.0 * float(logs[-1] - logs[-6]),
        2.0 * float(logs[-1] - logs[-WINDOW - 1]),
        10.0 * float(rets.std()),
        5.0 * (closes[-1] / float(np.mean(closes[1:])) - 1.0),
        1000.0 * (funding or 0.0),
    ]


def build_observation(view: MarketView, weights: Mapping[Asset, float]) -> Obs:
    """Features at the close of `view.t` plus current weights (cash = 1 - invested)."""
    features: list[float] = []
    for asset in view.assets:
        features.extend(_asset_features(view, asset))
    fear_greed = view.fear_greed
    features.append(0.0 if fear_greed is None else fear_greed / 100.0 - 0.5)
    held = [weights.get(a, 0.0) for a in view.assets]
    features.extend([*held, max(0.0, 1.0 - sum(held))])
    return np.clip(np.asarray(features, dtype=np.float32), -OBS_CLIP, OBS_CLIP)


def action_to_weights(action: NDArray[Any], assets: Sequence[Asset]) -> dict[Asset, float]:
    """Softmax over assets + cash (last entry); returns the asset weights, cash is implicit."""
    logits = LOGIT_SCALE * np.clip(np.asarray(action, dtype=np.float64), -1.0, 1.0)
    if logits.shape != (len(assets) + 1,):
        raise ValueError(f"expected {len(assets) + 1} action values, got shape {logits.shape}")
    exp = np.exp(logits - logits.max())
    probs = exp / exp.sum()
    return {a: float(p) for a, p in zip(assets, probs[:-1], strict=True)}


class TradingEnv(gym.Env[Obs, Action]):
    """One episode walks decision days `t` from its start to `end - 1` (executing up to `end`).

    With `episode_length` set, each reset starts at a random day (drawn from the seeded
    `np_random`), which gives PPO many shorter episodes over the training window.
    """

    metadata: dict[str, Any] = {"render_modes": []}  # noqa: RUF012 (gymnasium's own type)

    def __init__(
        self,
        market: MarketData,
        *,
        start: int = 0,
        end: int | None = None,
        costs: ExecutionCosts | None = None,
        initial_cash: float = DEFAULT_INITIAL_CASH,
        turnover_penalty: float = 0.0,
        episode_length: int | None = None,
    ) -> None:
        super().__init__()
        self.market = market
        self.start = start
        self.end = len(market) - 1 if end is None else end
        if not 0 <= start < self.end <= len(market) - 1:
            raise ValueError("need 0 <= start < end <= len(market) - 1")
        if episode_length is not None and not 1 <= episode_length <= self.end - start:
            raise ValueError("episode_length must fit between start and end")
        if turnover_penalty < 0:
            raise ValueError("turnover_penalty must be >= 0")
        self.costs = costs or ExecutionCosts()
        self.initial_cash = initial_cash
        self.turnover_penalty = turnover_penalty
        self.episode_length = episode_length
        n = len(market.assets)
        self.observation_space = spaces.Box(
            -OBS_CLIP, OBS_CLIP, shape=(observation_size(n),), dtype=np.float32
        )
        self.action_space = spaces.Box(-1.0, 1.0, shape=(n + 1,), dtype=np.float32)
        self.t = start
        self.episode_end = self.end
        self.portfolio = Portfolio(initial_cash)

    def _closes(self, t: int) -> dict[Asset, float]:
        return {a: self.market.bars[a][t].close for a in self.market.assets}

    def _observe(self) -> Obs:
        weights = self.portfolio.weights(self._closes(self.t))
        return build_observation(MarketView(self.market, self.t), weights)

    def reset(
        self, *, seed: int | None = None, options: dict[str, Any] | None = None
    ) -> tuple[Obs, dict[str, Any]]:
        super().reset(seed=seed)
        if self.episode_length is None:
            self.t = self.start
        else:
            last_start = self.end - self.episode_length
            self.t = int(self.np_random.integers(self.start, last_start + 1))
        self.episode_end = self.end if self.episode_length is None else self.t + self.episode_length
        self.portfolio = Portfolio(self.initial_cash)
        return self._observe(), {"day": self.market.days[self.t], "equity": self.initial_cash}

    def step(self, action: Action) -> tuple[Obs, SupportsFloat, bool, bool, dict[str, Any]]:
        t = self.t
        equity_before = self.portfolio.value(self._closes(t))
        targets = action_to_weights(action, self.market.assets)
        open_next = {a: self.market.bars[a][t + 1].open for a in self.market.assets}
        self.portfolio, fills = rebalance(
            self.portfolio, targets, open_next, self.costs, self.market.days[t + 1]
        )
        self.t = t + 1
        equity = self.portfolio.value(self._closes(self.t))
        turnover = sum(f.quantity * f.price for f in fills) / equity_before
        reward = math.log(equity / equity_before) - self.turnover_penalty * turnover
        info = {
            "day": self.market.days[self.t],
            "equity": equity,
            "turnover": turnover,
            "fees": sum(f.fee for f in fills),
        }
        # Running out of data is a time limit, not a terminal state of the MDP.
        return self._observe(), reward, False, self.t >= self.episode_end, info
