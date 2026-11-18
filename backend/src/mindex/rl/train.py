"""PPO training on the train split with model selection on the validation split (never test).

Training runs in chunks of `eval_every` steps; after each chunk the deterministic policy is
evaluated over the whole validation window and the best one is kept. The artefact directory
holds `model.zip` and `manifest.json` (seed, hyperparameters, periods, validation history,
library versions and the model's SHA-256), which `PPOAgent.from_artifact` verifies on load.
"""

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date
from importlib.metadata import version
from pathlib import Path
from typing import Any

from mindex.rl.env import FEATURES_VERSION, TradingEnv
from mindex.rl.policy import Policy, sb3

MODEL_FILE = "model.zip"
MANIFEST_FILE = "manifest.json"


@dataclass(frozen=True, slots=True)
class PPOHyperparams:
    """SB3 PPO defaults, with a smaller rollout (daily data has only ~1 800 training days)."""

    total_timesteps: int = 200_000
    eval_every: int = 10_240  # steps between validation evaluations (a multiple of n_steps)
    n_steps: int = 1024
    batch_size: int = 64
    n_epochs: int = 10
    learning_rate: float = 3e-4
    gamma: float = 0.99
    gae_lambda: float = 0.95
    clip_range: float = 0.2
    ent_coef: float = 0.0
    net_arch: tuple[int, ...] = (64, 64)
    episode_length: int | None = 180  # random training episodes of ~6 months
    turnover_penalty: float = 0.0

    def __post_init__(self) -> None:
        if min(self.total_timesteps, self.eval_every, self.n_steps, self.batch_size) < 1:
            raise ValueError("step counts must be positive")
        if self.batch_size > self.n_steps:
            raise ValueError("batch_size must not exceed n_steps")


@dataclass(frozen=True, slots=True)
class EvalResult:
    log_return: float  # sum of daily log returns after costs (turnover penalty excluded)
    final_equity: float
    mean_turnover: float
    days: int


def evaluate(policy: Policy, env: TradingEnv) -> EvalResult:
    """Run one deterministic episode and report its net log return."""
    obs, info = env.reset(seed=0)
    start_equity = float(info["equity"])
    equity, turnover, days = start_equity, 0.0, 0
    truncated = False
    while not truncated:
        action, _ = policy.predict(obs, deterministic=True)
        obs, _, _, truncated, info = env.step(action)
        equity = float(info["equity"])
        turnover += float(info["turnover"])
        days += 1
    return EvalResult(math.log(equity / start_equity), equity, turnover / days, days)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_manifest(out_dir: Path, manifest: Mapping[str, Any]) -> None:
    text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    (out_dir / MANIFEST_FILE).write_text(text, encoding="utf-8", newline="\n")


def train_ppo(
    train_env: TradingEnv,
    val_env: TradingEnv,
    hp: PPOHyperparams,
    *,
    seed: int,
    out_dir: Path,
    periods: Mapping[str, tuple[date, date]],
) -> dict[str, Any]:
    """Train, keep the best validation checkpoint in `out_dir`, and return its manifest."""
    lib = sb3()
    model = lib.PPO(
        "MlpPolicy",
        train_env,
        learning_rate=hp.learning_rate,
        n_steps=hp.n_steps,
        batch_size=hp.batch_size,
        n_epochs=hp.n_epochs,
        gamma=hp.gamma,
        gae_lambda=hp.gae_lambda,
        clip_range=hp.clip_range,
        ent_coef=hp.ent_coef,
        policy_kwargs={"net_arch": list(hp.net_arch)},
        seed=seed,
        device="cpu",  # an MLP on daily data is faster on CPU than on a GPU
        verbose=0,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    model_path = out_dir / MODEL_FILE
    history: list[dict[str, Any]] = []
    best: dict[str, Any] | None = None
    while (done := int(model.num_timesteps)) < hp.total_timesteps:
        model.learn(min(hp.eval_every, hp.total_timesteps - done), reset_num_timesteps=done == 0)
        result = evaluate(model, val_env)
        entry = {"timesteps": int(model.num_timesteps), **asdict(result)}
        history.append(entry)
        if best is None or result.log_return > best["log_return"]:
            best = entry
            model.save(str(model_path))
    manifest: dict[str, Any] = {
        "algorithm": "PPO",
        "seed": seed,
        "features_version": FEATURES_VERSION,
        "assets": [str(a) for a in train_env.market.assets],
        "hyperparams": asdict(hp),
        "periods": {k: [d.isoformat() for d in v] for k, v in periods.items()},
        "selection": "best validation log return (deterministic policy)",
        "best": best,
        "history": history,
        "versions": {p: version(p) for p in ("stable-baselines3", "torch", "gymnasium")},
        "files": {MODEL_FILE: sha256_file(model_path)},
    }
    write_manifest(out_dir, manifest)
    return manifest
