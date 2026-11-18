"""The narrow interface Mindex needs from a trained SB3 policy, and the one place SB3 is loaded.

`stable_baselines3` (and torch with it) lives in the optional `rl` dependency group. It is
imported with `importlib` on first use, never at module import, so the API, the simulator and
the rule/LLM agents run without it. The dynamic import also keeps pyright's result the same
whether the group is installed (CI) or not (local): SB3's types never leak past `Policy`.
"""

import importlib
from pathlib import Path
from types import ModuleType
from typing import Any, Protocol, cast

from mindex.rl.env import Obs


class Policy(Protocol):
    def predict(self, observation: Obs, *, deterministic: bool = ...) -> tuple[Any, Any]: ...


def sb3() -> ModuleType:
    """Import stable_baselines3 lazily, with an actionable message when the group is missing."""
    try:
        return importlib.import_module("stable_baselines3")
    except ImportError as exc:
        raise RuntimeError(
            "stable-baselines3 is not installed; run `uv sync --group rl` (PPO training machine)"
        ) from exc


def load_policy(path: Path) -> Policy:
    """Load a saved SB3 PPO model on CPU. Only load trusted files: the zip holds pickles."""
    return cast(Policy, sb3().PPO.load(str(path), device="cpu"))
