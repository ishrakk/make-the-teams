"""The search: find a low-cost split.

The hard rule, team sizes within one of each other, is built in: the search
starts with even teams and only ever swaps players, so sizes never change.
Everything else is a preference, handled by the cost function in cost.py.

Method: hill climbing with random restarts.
  1. Shuffle the players into two even teams. Odd-numbered attempts start with
     everyone on their primary position. Even-numbered attempts start with each
     player who has a secondary position on it with a 50% chance. The search
     needs both: each one gets stuck on rosters where the other does not.
  2. Try swapping two players between teams, or moving one player between
     primary and secondary. Keep any change that lowers the cost.
  3. Stop when no single change helps. That is one attempt.
  4. Make RESTARTS attempts. Keep every result within TOLERANCE of the best, then
     pick one of those at random.

The tolerance is what makes "reshuffle" work. Ratings make exact ties rare, so
always taking the very best split would give the same teams every time. Nobody
can notice a difference this small, so it's better spent on variety.
"""

from __future__ import annotations

import random
import secrets
from collections.abc import Iterable

from app.splitter.cost import DEFAULT_WEIGHTS, CostBreakdown, Weights, score
from app.splitter.models import Assignment, Player, Position, SplitResult

# Measured by benchmark.py; see "How good is the search?" in README.md.
RESTARTS = 150
TOLERANCE = 1.0  # How far above the best cost a split can be and still be picked.

_DISPLAY_ORDER = {position: index for index, position in enumerate(Position)}


class _State:
    """One candidate split, with position counts kept up to date for fast scoring."""

    def __init__(
        self,
        players: list[Player],
        team_of: list[int],
        weights: Weights,
        skill: list[float],
    ):
        self.players = players
        self.skill = skill
        self.team_of = team_of
        self.position_of = [player.primary for player in players]
        self.weights = weights
        self.off_position = 0
        self.counts = [{position: 0 for position in Position} for _ in range(2)]
        for team, position in zip(team_of, self.position_of, strict=True):
            self.counts[team][position] += 1
        self.rating_advantage = sum(
            value if team == 0 else -value for team, value in zip(team_of, skill, strict=True)
        )

    def breakdown(self) -> CostBreakdown:
        return score(
            self.counts[0],
            self.counts[1],
            self.off_position,
            self.weights,
            self.rating_advantage,
        )

    def cost(self) -> float:
        return self.breakdown().total

    def swap(self, i: int, j: int) -> None:
        """Exchange the teams of players i and j. Calling it twice undoes it."""
        team_i, team_j = self.team_of[i], self.team_of[j]
        position_i, position_j = self.position_of[i], self.position_of[j]
        self.counts[team_i][position_i] -= 1
        self.counts[team_j][position_i] += 1
        self.counts[team_j][position_j] -= 1
        self.counts[team_i][position_j] += 1
        self.team_of[i], self.team_of[j] = team_j, team_i
        # Player i moved from team_i to team_j, and player j the other way.
        direction = 1 if team_i == 0 else -1
        self.rating_advantage += 2 * direction * (self.skill[j] - self.skill[i])

    def toggle_position(self, i: int) -> None:
        """Move player i between primary and secondary. Calling it twice undoes it."""
        player = self.players[i]
        current = self.position_of[i]
        new = player.secondary if current == player.primary else player.primary
        team = self.counts[self.team_of[i]]
        team[current] -= 1
        team[new] += 1
        self.position_of[i] = new
        self.off_position += 1 if new != player.primary else -1


def _climb(state: _State, rng: random.Random) -> float:
    """Apply improving changes until none is left. Returns the final cost."""
    n = len(state.players)
    best = state.cost()
    improved = True
    while improved:
        improved = False
        moves = [("swap", i, j) for i in range(n) for j in range(i + 1, n)]
        moves += [("toggle", i, i) for i in range(n) if state.players[i].secondary]
        rng.shuffle(moves)
        for kind, i, j in moves:
            if kind == "swap":
                if state.team_of[i] == state.team_of[j]:
                    continue
                state.swap(i, j)
                cost = state.cost()
                if cost < best:
                    best, improved = cost, True
                else:
                    state.swap(i, j)
            else:
                state.toggle_position(i)
                cost = state.cost()
                if cost < best:
                    best, improved = cost, True
                else:
                    state.toggle_position(i)
    return best


def _relative_skill(roster: list[Player]) -> list[float]:
    """Each player's rating relative to the average, with unrated players at 0.

    Using relative ratings means a team that's a player short isn't unfairly
    scored for having a lower total.
    """
    ratings = [player.rating for player in roster if player.rating is not None]
    if not ratings:
        return [0.0] * len(roster)
    average = sum(ratings) / len(ratings)
    return [0.0 if player.rating is None else player.rating - average for player in roster]


def _sorted_team(assignments: list[Assignment]) -> tuple[Assignment, ...]:
    return tuple(
        sorted(assignments, key=lambda a: (_DISPLAY_ORDER[a.position], a.player.name.lower()))
    )


def _warnings(team_a: tuple[Assignment, ...], team_b: tuple[Assignment, ...]) -> tuple[str, ...]:
    """Problems a group admin should know about, in plain words."""
    notes = []
    if len(team_a) != len(team_b):
        notes.append(
            f"Odd number of players ({len(team_a) + len(team_b)}): Team B is one player short."
        )
    for label, team in (("A", team_a), ("B", team_b)):
        keepers = sum(1 for a in team if a.position == Position.GK)
        if keepers == 0:
            notes.append(f"Team {label} has no keeper. They will need to rotate.")
        elif keepers > 1:
            notes.append(f"Team {label} has {keepers} keepers. They will need to rotate.")
    return tuple(notes)


def split_teams(
    players: Iterable[Player],
    seed: int | None = None,
    weights: Weights = DEFAULT_WEIGHTS,
    tolerance: float = TOLERANCE,
) -> SplitResult:
    """Split players into two teams.

    The same players, seed and weights always give the same teams, whatever
    order the players are passed in. With seed=None a random seed is chosen and
    returned in the result. If the team sizes are unequal, Team A is the larger.

    Raises ValueError with fewer than 2 players, or if a player id is repeated.
    """
    roster = sorted(players, key=lambda player: str(player.id))
    if len(roster) < 2:
        raise ValueError("Need at least 2 players to make teams.")
    if len({str(player.id) for player in roster}) != len(roster):
        raise ValueError("Each player can only be listed once.")

    if seed is None:
        seed = secrets.randbits(32)
    rng = random.Random(seed)

    n = len(roster)
    skill = _relative_skill(roster)
    attempts: list[tuple[float, _State]] = []
    for attempt in range(RESTARTS):
        team_of = [index % 2 for index in range(n)]  # Team A gets the extra player if n is odd.
        rng.shuffle(team_of)
        state = _State(roster, team_of, weights, skill)
        if attempt % 2:
            for index, player in enumerate(roster):
                if player.secondary and rng.random() < 0.5:
                    state.toggle_position(index)
        attempts.append((_climb(state, rng), state))

    best_cost = min(cost for cost, _ in attempts)
    close_enough = [state for cost, state in attempts if cost <= best_cost + tolerance + 1e-9]
    best_state = rng.choice(close_enough)

    teams: list[list[Assignment]] = [[], []]
    for index, player in enumerate(roster):
        teams[best_state.team_of[index]].append(Assignment(player, best_state.position_of[index]))
    team_a, team_b = _sorted_team(teams[0]), _sorted_team(teams[1])

    return SplitResult(
        team_a=team_a,
        team_b=team_b,
        seed=seed,
        cost=best_state.breakdown(),
        warnings=_warnings(team_a, team_b),
    )
