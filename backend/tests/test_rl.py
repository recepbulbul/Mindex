"""Torch-free tests for the Gymnasium environment, PPO agent plumbing and the train-ppo CLI."""

import json
import math
import subprocess
import sys
from dataclasses import replace
from datetime import date
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from gymnasium.utils.env_checker import check_env
from numpy.typing import NDArray

from conftest import synthetic_frame
from mindex import cli
from mindex.agents.base import AgentKind
from mindex.agents.ppo import ArtifactError, PPOAgent
from mindex.data.splits import Split
from mindex.domain.decision import Allocation, Asset, Decision
from mindex.rl import policy as rl_policy
from mindex.rl.env import (
    FEATURES_VERSION,
    TradingEnv,
    action_to_weights,
    build_observation,
    observation_size,
)
from mindex.rl.train import (
    MANIFEST_FILE,
    MODEL_FILE,
    PPOHyperparams,
    evaluate,
    sha256_file,
    write_manifest,
)
from mindex.sim.engine import ExecutionCosts, Observation, Portfolio, Simulator, rebalance
from mindex.sim.market import Bar, MarketData, MarketView

Action = NDArray[np.float32]


def _actions(n: int, size: int, seed: int = 7) -> list[Action]:
    rng = np.random.default_rng(seed)
    return [rng.uniform(-1, 1, size).astype(np.float32) for _ in range(n)]


class FixedPolicy:
    """Stands in for an SB3 model: replays a fixed action (and records what it saw)."""

    def __init__(self, action: Action) -> None:
        self.action = action
        self.seen: list[NDArray[np.float32]] = []

    def predict(self, observation: NDArray[np.float32], *, deterministic: bool = False) -> Any:
        assert deterministic
        self.seen.append(observation)
        return self.action, None


class ScriptedAgent:
    """Simulator agent that turns the env's action for each step into a Decision."""

    agent_id = "scripted"

    def __init__(self, actions: list[Action], assets: tuple[Asset, ...]) -> None:
        self.actions = actions
        self.assets = assets

    def decide(self, obs: Observation) -> Decision:
        weights = action_to_weights(self.actions[obs.step], self.assets)
        return Decision(
            allocations=[Allocation(asset=a, weight=w) for a, w in weights.items()],
            confidence=1.0,
            rationale="test: senaryolu eylem",
        )


def test_env_passes_gymnasium_checker(market: MarketData) -> None:
    env = TradingEnv(market, episode_length=10)
    check_env(env, skip_render_check=True)
    assert env.observation_space.shape == (observation_size(len(market.assets)),)
    assert env.action_space.shape == (len(market.assets) + 1,)


def test_action_reaches_simplex_corners() -> None:
    assets = (Asset.BTC, Asset.ETH)
    all_btc = action_to_weights(np.array([1.0, -1.0, -1.0]), assets)
    all_cash = action_to_weights(np.array([-1.0, -1.0, 1.0]), assets)
    assert all_btc[Asset.BTC] > 0.999
    assert sum(all_cash.values()) < 0.001
    even = action_to_weights(np.zeros(3), assets)
    assert even == pytest.approx({Asset.BTC: 1 / 3, Asset.ETH: 1 / 3})
    with pytest.raises(ValueError, match="action values"):
        action_to_weights(np.zeros(2), assets)


def test_env_step_equals_rebalance(market: MarketData) -> None:
    costs = ExecutionCosts()
    env = TradingEnv(market, start=35, costs=costs)
    env.reset(seed=0)
    action = np.array([0.5, 0.2, -0.3], dtype=np.float32)
    _, reward, terminated, truncated, info = env.step(action)

    targets = action_to_weights(action, market.assets)
    opens = {a: market.bars[a][36].open for a in market.assets}
    expected, fills = rebalance(Portfolio(10_000.0), targets, opens, costs, market.days[36])
    closes = {a: market.bars[a][36].close for a in market.assets}
    assert env.portfolio == expected
    assert info["equity"] == expected.value(closes)
    assert info["fees"] == sum(f.fee for f in fills) > 0
    assert reward == math.log(expected.value(closes) / 10_000.0)
    assert (terminated, truncated) == (False, False)


def test_env_equity_matches_simulator(market: MarketData) -> None:
    """Same actions through the env and the simulator: identical equity path, day for day."""
    start = 31
    actions = _actions(len(market) - 1 - start, len(market.assets) + 1)
    sim = Simulator(market, [ScriptedAgent(actions, market.assets)], start=start)
    book = sim.run().books["scripted"]

    env = TradingEnv(market, start=start)
    env.reset(seed=0)
    equity = [env.initial_cash]
    rewards: list[float] = []
    truncated = False
    for action in actions:
        assert not truncated
        _, reward, _, truncated, info = env.step(action)
        equity.append(info["equity"])
        rewards.append(float(reward))
    assert truncated
    assert equity == pytest.approx(book.equity, rel=1e-12)
    # Reward = close-to-close log return of equity, on every step (not only the first).
    expected = [math.log(b / a) for a, b in zip(book.equity, book.equity[1:], strict=False)]
    assert rewards == pytest.approx(expected, rel=1e-9, abs=1e-15)
    assert env.portfolio.holdings == pytest.approx(dict(book.portfolio.holdings), rel=1e-12)


class LinearPolicy:
    """Torch-free stand-in whose action depends on the observation; records what it saw."""

    def __init__(self, n_obs: int, n_act: int) -> None:
        self.w = np.random.default_rng(11).normal(0, 1, (n_act, n_obs))
        self.seen: list[list[float]] = []

    def predict(self, observation: NDArray[np.float32], *, deterministic: bool = False) -> Any:
        self.seen.append(observation.tolist())
        return np.tanh(self.w @ observation).astype(np.float32), None


def test_ppo_agent_in_simulator_matches_env(market: MarketData) -> None:
    """Env and Simulator+PPOAgent: bit-identical observations (weights included) and equity."""
    start = 31
    n_obs, n_act = observation_size(len(market.assets)), len(market.assets) + 1
    in_env, in_sim = LinearPolicy(n_obs, n_act), LinearPolicy(n_obs, n_act)

    env = TradingEnv(market, start=start)
    obs, _ = env.reset(seed=0)
    equity = [env.initial_cash]
    truncated = False
    while not truncated:
        action, _ = in_env.predict(obs, deterministic=True)
        obs, _, _, truncated, info = env.step(action)
        equity.append(info["equity"])

    book = Simulator(market, [PPOAgent(in_sim, market.assets)], start=start).run().books["ppo"]
    assert in_sim.seen == in_env.seen
    assert book.equity == equity
    assert any(0.0 < w < 1.0 for row in in_env.seen for w in row[-3:-1])  # weights are live


def test_observation_and_action_are_clipped(market: MarketData) -> None:
    wild = replace(market, funding={a: (0.5,) * len(market) for a in market.assets})
    obs = build_observation(MarketView(wild, 40), {})
    assert obs.max() == 5.0
    assert TradingEnv(wild).observation_space.contains(obs)
    assets = market.assets
    big = action_to_weights(np.array([7.0, -3.0, 0.5]), assets)
    assert big == action_to_weights(np.array([1.0, -1.0, 0.5]), assets)


def test_turnover_penalty_lowers_reward(market: MarketData) -> None:
    action = np.array([1.0, 0.0, -1.0], dtype=np.float32)
    rewards: list[float] = []
    turnover = 0.0
    for penalty in (0.0, 0.01):
        env = TradingEnv(market, start=31, turnover_penalty=penalty)
        env.reset(seed=0)
        _, reward, _, _, info = env.step(action)
        rewards.append(float(reward))
        turnover = info["turnover"]
    assert turnover > 0.9
    assert rewards[1] == pytest.approx(rewards[0] - 0.01 * turnover)


def _perturb_after(market: MarketData, t: int) -> MarketData:
    """Same market through day `t`, wildly different afterwards."""
    bars = {
        a: tuple(
            b if i <= t else Bar(b.open * 3, b.high * 3, b.low * 0.1, b.close * 0.2, 0.0)
            for i, b in enumerate(series)
        )
        for a, series in market.bars.items()
    }
    funding = {
        a: tuple(f if i <= t else 0.5 for i, f in enumerate(s)) for a, s in market.funding.items()
    }
    fear_greed = tuple(g if i <= t else 99 for i, g in enumerate(market.fear_greed))
    return replace(market, bars=bars, funding=funding, fear_greed=fear_greed)


def test_observations_have_no_look_ahead(market: MarketData) -> None:
    t = 40
    other = _perturb_after(market, t)
    assert build_observation(MarketView(market, t), {}).tolist() == (
        build_observation(MarketView(other, t), {}).tolist()
    )
    envs = [TradingEnv(m, start=31) for m in (market, other)]
    obs = [e.reset(seed=0)[0] for e in envs]
    for action in _actions(t - 31, len(market.assets) + 1):
        assert obs[0].tolist() == obs[1].tolist()
        obs = [e.step(action)[0] for e in envs]
    assert envs[0].t == t
    assert obs[0].tolist() == obs[1].tolist()  # observation at the close of t
    step_a, step_b = (e.step(np.zeros(3, dtype=np.float32))[0] for e in envs)
    assert step_a.tolist() != step_b.tolist()  # t+1 differs, so the test can tell


def test_observation_shape_on_short_history(market: MarketData) -> None:
    obs = build_observation(MarketView(market, 0), {Asset.BTC: 0.25})
    assert obs.shape == (observation_size(2),)
    assert np.isfinite(obs).all()
    assert obs[-3:].tolist() == pytest.approx([0.25, 0.0, 0.75])


def test_reset_is_deterministic(market: MarketData) -> None:
    env = TradingEnv(market, episode_length=10)
    first = env.reset(seed=3)
    t_first = env.t
    second = env.reset(seed=3)
    assert env.t == t_first
    assert first[0].tolist() == second[0].tolist()
    starts = {(env.reset(seed=s), env.t)[1] for s in range(20)}
    assert len(starts) > 1
    assert all(0 <= s <= len(market) - 1 - 10 for s in starts)
    for _ in range(9):
        assert not env.step(np.zeros(3, dtype=np.float32))[3]
    assert env.step(np.zeros(3, dtype=np.float32))[3]  # truncated after 10 days


def test_env_validates_arguments(market: MarketData) -> None:
    with pytest.raises(ValueError, match="start < end"):
        TradingEnv(market, start=59)
    with pytest.raises(ValueError, match="episode_length"):
        TradingEnv(market, start=50, episode_length=20)
    with pytest.raises(ValueError, match="turnover_penalty"):
        TradingEnv(market, turnover_penalty=-1)


def test_hyperparams_validation() -> None:
    with pytest.raises(ValueError, match="batch_size"):
        PPOHyperparams(n_steps=32, batch_size=64)
    with pytest.raises(ValueError, match="positive"):
        PPOHyperparams(total_timesteps=0)


def test_evaluate_runs_one_full_episode(market: MarketData) -> None:
    env = TradingEnv(market, start=31)
    result = evaluate(FixedPolicy(np.array([1.0, -1.0, -1.0], dtype=np.float32)), env)
    assert result.days == len(market) - 1 - 31
    assert result.log_return == pytest.approx(math.log(result.final_equity / 10_000.0))
    btc = market.bars[Asset.BTC]
    assert result.log_return > 0.9 * math.log(btc[-1].close / btc[32].open)  # rides BTC's trend


def _artifact(tmp_path: Path, **override: Any) -> Path:
    tmp_path.mkdir(parents=True)
    (tmp_path / MODEL_FILE).write_bytes(b"fake model")
    manifest = {
        "features_version": FEATURES_VERSION,
        "assets": ["BTC", "ETH"],
        "files": {MODEL_FILE: sha256_file(tmp_path / MODEL_FILE)},
        **override,
    }
    write_manifest(tmp_path, manifest)
    return tmp_path


def test_ppo_agent_decides_from_shared_observation(market: MarketData) -> None:
    policy = FixedPolicy(np.array([1.0, 0.5, -1.0], dtype=np.float32))
    agent = PPOAgent(policy, market.assets)
    assert agent.kind is AgentKind.RL
    view = MarketView(market, 40)
    decision = agent.decide(Observation(view, 9, Portfolio(10_000.0), {}, 10_000.0))
    assert decision.total_weight <= 1.0
    assert decision.weights() == pytest.approx(
        action_to_weights(policy.action, market.assets), abs=1e-4
    )
    assert policy.seen[0].tolist() == build_observation(view, {}).tolist()


def test_ppo_agent_runs_in_simulator(market: MarketData) -> None:
    agent = PPOAgent(FixedPolicy(np.array([0.2, 0.1, 0.0], dtype=np.float32)), market.assets)
    state = Simulator(market, [agent], start=31).run()
    assert state.books["ppo"].decisions == len(market) - 1 - 31
    assert state.books["ppo"].fills


def test_ppo_agent_rejects_other_assets(market: MarketData) -> None:
    agent = PPOAgent(FixedPolicy(np.zeros(3, dtype=np.float32)), (Asset.BTC, Asset.SOL))
    obs = Observation(MarketView(market, 40), 0, Portfolio(1.0), {}, 1.0)
    with pytest.raises(ValueError, match="trained on"):
        agent.decide(obs)


def test_from_artifact_checks_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    loaded: list[Path] = []

    def fake_load(path: Path) -> FixedPolicy:
        loaded.append(path)
        return FixedPolicy(np.zeros(3, dtype=np.float32))

    monkeypatch.setattr("mindex.agents.ppo.load_policy", fake_load)
    agent = PPOAgent.from_artifact(_artifact(tmp_path / "ok"), agent_id="ppo-1")
    assert (agent.agent_id, agent.assets) == ("ppo-1", (Asset.BTC, Asset.ETH))
    assert loaded == [tmp_path / "ok" / MODEL_FILE]

    with pytest.raises(ArtifactError, match="SHA-256"):
        PPOAgent.from_artifact(_artifact(tmp_path / "tampered", files={MODEL_FILE: "0" * 64}))
    with pytest.raises(ArtifactError, match="features"):
        PPOAgent.from_artifact(_artifact(tmp_path / "old", features_version=0))
    assert len(loaded) == 1


def test_sb3_missing_gives_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing(name: str) -> None:
        raise ImportError(name)

    monkeypatch.setattr("mindex.rl.policy.importlib.import_module", missing)
    with pytest.raises(RuntimeError, match="--group rl"):
        rl_policy.load_policy(Path("model.zip"))


def test_importing_agents_and_cli_does_not_load_torch() -> None:
    code = (
        "import sys, mindex.agents.ppo, mindex.cli, mindex.rl.train; "
        "print(sorted(m for m in ('torch', 'stable_baselines3') if m in sys.modules))"
    )
    out = subprocess.run(  # noqa: S603 (fixed arguments, our own interpreter)
        [sys.executable, "-c", code], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


def test_train_ppo_cli_uses_train_and_validation_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    market = MarketData.from_frame(synthetic_frame(date(2025, 1, 1), 250))  # > episode_length
    splits: list[Split] = []
    calls: list[dict[str, Any]] = []

    def fake_market(snapshot: Path, split: Split, unseal: bool) -> tuple[MarketData, int]:
        assert not unseal
        splits.append(split)
        return market, 31

    def fake_train(
        train_env: TradingEnv, val_env: TradingEnv, hp: PPOHyperparams, **kw: Any
    ) -> Any:
        calls.append({"hp": hp, "train": train_env, "val": val_env, **kw})
        return {"seed": kw["seed"], "best": None, "files": {}}

    monkeypatch.setattr(cli, "_market", fake_market)
    monkeypatch.setattr("mindex.rl.train.train_ppo", fake_train)
    cli.main(["train-ppo", "--seed", "4", "--out", str(tmp_path), "--timesteps", "1000"])
    assert splits == [Split.TRAIN, Split.VALIDATION]
    (call,) = calls
    assert call["seed"] == 4
    assert call["out_dir"] == tmp_path / "seed-4"
    assert call["hp"].total_timesteps == 1000
    assert call["train"].episode_length == PPOHyperparams().episode_length
    assert call["val"].episode_length is None
    assert set(call["periods"]) == {"train", "validation"}


def test_train_ppo_cli_has_no_unseal_flag() -> None:
    with pytest.raises(SystemExit):
        cli.main(["train-ppo", "--unseal"])


def test_manifest_round_trip(tmp_path: Path) -> None:
    write_manifest(tmp_path, {"seed": 1, "ğ": "ü"})
    raw = (tmp_path / MANIFEST_FILE).read_bytes()
    assert b"\r\n" not in raw
    assert json.loads(raw) == {"seed": 1, "ğ": "ü"}
