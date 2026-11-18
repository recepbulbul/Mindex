"""PPO tests that need stable-baselines3 + torch (the `rl` group): skipped locally, run on CI."""

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from mindex.agents.ppo import PPOAgent
from mindex.domain.decision import Decision
from mindex.rl.env import TradingEnv
from mindex.rl.policy import load_policy
from mindex.rl.train import MODEL_FILE, PPOHyperparams, evaluate, sha256_file, train_ppo
from mindex.sim.engine import Observation, Portfolio, Simulator
from mindex.sim.market import MarketData, MarketView

pytest.importorskip("stable_baselines3")

SMOKE = PPOHyperparams(
    total_timesteps=256, eval_every=128, n_steps=128, batch_size=32, n_epochs=2, episode_length=20
)
TRAIN_END = 40  # synthetic market: days 0-40 train, 40-59 validation


def _train(market: MarketData, out: Path, seed: int = 0) -> dict[str, Any]:
    train_env = TradingEnv(market, end=TRAIN_END, episode_length=SMOKE.episode_length)
    val_env = TradingEnv(market, start=TRAIN_END)
    periods = {
        "train": (market.days[0], market.days[TRAIN_END]),
        "validation": (market.days[TRAIN_END], market.days[-1]),
    }
    return train_ppo(train_env, val_env, SMOKE, seed=seed, out_dir=out, periods=periods)


def test_smoke_training_writes_verified_artifact(market: MarketData, tmp_path: Path) -> None:
    manifest = _train(market, tmp_path / "run")
    model = tmp_path / "run" / MODEL_FILE
    assert manifest["files"] == {MODEL_FILE: sha256_file(model)}
    assert [h["timesteps"] for h in manifest["history"]] == [128, 256]
    assert manifest["best"] == max(manifest["history"], key=lambda h: h["log_return"])
    assert manifest["assets"] == ["BTC", "ETH"]


def test_saved_model_reproduces_its_validation_score(market: MarketData, tmp_path: Path) -> None:
    """Loading the artefact gives the policy that was selected, and same seed → same run."""
    first = _train(market, tmp_path / "a", seed=1)
    second = _train(market, tmp_path / "b", seed=1)
    assert first["history"] == second["history"]

    policy = load_policy(tmp_path / "a" / MODEL_FILE)
    score = evaluate(policy, TradingEnv(market, start=TRAIN_END)).log_return
    assert score == pytest.approx(first["best"]["log_return"], abs=1e-9)
    obs = TradingEnv(market, start=TRAIN_END).reset(seed=0)[0]
    a1, _ = policy.predict(obs, deterministic=True)
    a2, _ = load_policy(tmp_path / "a" / MODEL_FILE).predict(obs, deterministic=True)
    assert np.array_equal(a1, a2)


def test_ppo_agent_from_artifact_decides(market: MarketData, tmp_path: Path) -> None:
    _train(market, tmp_path / "run")
    agent = PPOAgent.from_artifact(tmp_path / "run")
    obs = Observation(MarketView(market, 45), 5, Portfolio(10_000.0), {}, 10_000.0)
    decision = agent.decide(obs)
    assert isinstance(decision, Decision)
    assert 0.0 <= decision.total_weight <= 1.0 + 1e-6
    assert agent.decide(obs) == decision  # deterministic
    state = Simulator(market, [agent], start=TRAIN_END).run()
    assert state.books["ppo"].decisions == len(market) - 1 - TRAIN_END
