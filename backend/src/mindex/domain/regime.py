"""Market regime labels shared by the regime model, agents, the database and the API."""

from enum import StrEnum


class Regime(StrEnum):
    BULL = "bull"
    BEAR = "bear"
    SIDEWAYS = "sideways"
