"""`BaseAgent`: the single interface rule, RL and LLM agents share (F9)."""

from abc import ABC, abstractmethod
from enum import StrEnum

from mindex.domain.decision import Decision
from mindex.sim.engine import Observation


class AgentKind(StrEnum):
    RULE = "rule"
    RL = "rl"
    LLM = "llm"
    EXTERNAL = "external"


class BaseAgent(ABC):
    """A trading agent. `decide` must depend only on the observation, so runs are reproducible
    and a checkpointed simulation resumes identically."""

    kind: AgentKind

    def __init__(self, agent_id: str) -> None:
        self._agent_id = agent_id

    @property
    def agent_id(self) -> str:
        return self._agent_id

    @abstractmethod
    def decide(self, obs: Observation) -> Decision | None:
        """Target weights for the next open, or None to keep the current portfolio."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.agent_id!r})"
