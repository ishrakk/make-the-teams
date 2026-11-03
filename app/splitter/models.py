"""Data types going in and out of the splitter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.splitter.cost import CostBreakdown


class Position(str, Enum):
    GK = "GK"
    DEF = "DEF"
    MID = "MID"
    FWD = "FWD"


@dataclass(frozen=True)
class Player:
    """A player and the positions they are willing to play."""

    id: int | str
    name: str
    primary: Position
    secondary: Position | None = None


@dataclass(frozen=True)
class Assignment:
    """A player and the position they were given."""

    player: Player
    position: Position

    @property
    def on_secondary(self) -> bool:
        return self.position != self.player.primary


@dataclass(frozen=True)
class SplitResult:
    team_a: tuple[Assignment, ...]
    team_b: tuple[Assignment, ...]
    seed: int
    cost: CostBreakdown
    warnings: tuple[str, ...]
