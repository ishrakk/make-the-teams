"""The cost function: what makes one split better than another.

This file is the policy. To change what a good split means, change the weights
or add a term here. search.py only looks for the lowest cost and needs no
changes. Lower is better, and 0 would be a perfect split.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.splitter.models import Position

OUTFIELD = (Position.DEF, Position.MID, Position.FWD)


@dataclass(frozen=True)
class Weights:
    """How much each kind of problem matters, relative to the others."""

    missing_keeper: float = 100.0  # per team with no keeper
    extra_keeper: float = 20.0  # per keeper beyond the first on a team
    position_imbalance: float = 5.0  # per outfield position: (A count - B count) squared
    shape: float = 1.0  # per team and position: (actual - ideal count) squared
    off_position: float = 2.0  # per player on their secondary position

    # Ideal share of a team's outfield players in each position (4-3-3 by default).
    formation: dict[Position, float] = field(
        default_factory=lambda: {Position.DEF: 0.4, Position.MID: 0.3, Position.FWD: 0.3}
    )


DEFAULT_WEIGHTS = Weights()


@dataclass(frozen=True)
class CostBreakdown:
    """Weighted cost of each term, so a result can explain itself."""

    missing_keeper: float
    extra_keeper: float
    position_imbalance: float
    shape: float
    off_position: float

    @property
    def total(self) -> float:
        return (
            self.missing_keeper
            + self.extra_keeper
            + self.position_imbalance
            + self.shape
            + self.off_position
        )


def score(
    team_a: dict[Position, int],
    team_b: dict[Position, int],
    off_position_count: int,
    weights: Weights = DEFAULT_WEIGHTS,
) -> CostBreakdown:
    """Score a split from how many players each team has in each position."""
    missing = 0
    extra = 0
    shape = 0.0
    for team in (team_a, team_b):
        keepers = team[Position.GK]
        if keepers == 0:
            missing += 1
        else:
            extra += keepers - 1

        outfield_players = sum(team[position] for position in OUTFIELD)
        for position in OUTFIELD:
            ideal = weights.formation[position] * outfield_players
            shape += (team[position] - ideal) ** 2

    imbalance = sum((team_a[position] - team_b[position]) ** 2 for position in OUTFIELD)

    return CostBreakdown(
        missing_keeper=weights.missing_keeper * missing,
        extra_keeper=weights.extra_keeper * extra,
        position_imbalance=weights.position_imbalance * imbalance,
        shape=weights.shape * shape,
        off_position=weights.off_position * off_position_count,
    )
