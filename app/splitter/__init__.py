"""Team-splitting logic. Standard library only: no database or web imports.

See README.md in this directory for how it works and how to tune it.
"""

from app.splitter.cost import DEFAULT_WEIGHTS, CostBreakdown, Weights
from app.splitter.models import Assignment, Player, Position, SplitResult
from app.splitter.search import split_teams

__all__ = [
    "DEFAULT_WEIGHTS",
    "Assignment",
    "CostBreakdown",
    "Player",
    "Position",
    "SplitResult",
    "Weights",
    "split_teams",
]
