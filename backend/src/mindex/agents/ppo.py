"""PPO agent: a trained SB3 policy acting through the same observation as `TradingEnv`.

Importing this module does not import torch or stable_baselines3; they load only when
`from_artifact` reads a model (see `mindex.rl.policy`).
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np

from mindex.agents.base import AgentKind, BaseAgent
from mindex.domain.decision import Allocation, Asset, Decision
from mindex.rl.env import FEATURES_VERSION, action_to_weights, build_observation
from mindex.rl.policy import Policy, load_policy
from mindex.rl.train import MANIFEST_FILE, MODEL_FILE, sha256_file
from mindex.sim.engine import Observation

SHOWN_WEIGHT = 1e-3  # weights below this are left out of the rationale text (not the decision)


class ArtifactError(ValueError):
    """The model artefact does not match its manifest or this code's feature version."""


class PPOAgent(BaseAgent):
    kind = AgentKind.RL

    def __init__(self, policy: Policy, assets: Sequence[Asset], agent_id: str = "ppo") -> None:
        super().__init__(agent_id)
        self.policy = policy
        self.assets = tuple(assets)

    @classmethod
    def from_artifact(cls, directory: Path, agent_id: str = "ppo") -> "PPOAgent":
        """Load `model.zip` after checking its SHA-256 and feature version in the manifest."""
        manifest = cast(
            dict[str, Any], json.loads((directory / MANIFEST_FILE).read_text(encoding="utf-8"))
        )
        if manifest["features_version"] != FEATURES_VERSION:
            raise ArtifactError(
                f"model was trained on features v{manifest['features_version']}, "
                f"this code builds v{FEATURES_VERSION}; retrain it"
            )
        model_path = directory / MODEL_FILE
        if sha256_file(model_path) != manifest["files"][MODEL_FILE]:
            raise ArtifactError(f"{model_path} does not match the SHA-256 in its manifest")
        assets = [Asset(a) for a in cast(list[str], manifest["assets"])]
        return cls(load_policy(model_path), assets, agent_id)

    def decide(self, obs: Observation) -> Decision:
        if obs.view.assets != self.assets:
            raise ValueError(f"policy trained on {self.assets}, market has {obs.view.assets}")
        x = build_observation(obs.view, obs.weights)
        action, _ = self.policy.predict(x, deterministic=True)
        weights = action_to_weights(np.asarray(action), self.assets)
        # Every softmax weight goes into the decision, exactly what TradingEnv executes in training.
        allocations = [Allocation(asset=a, weight=w) for a, w in weights.items()]
        cash = 1.0 - sum(weights.values())
        shown = ", ".join(f"{a} %{100 * w:.1f}" for a, w in weights.items() if w >= SHOWN_WEIGHT)
        return Decision(
            allocations=allocations,
            confidence=1.0,
            rationale=f"PPO politikası (deterministik): nakit %{100 * cash:.1f}"
            + (f", {shown}" if shown else ""),
        )
