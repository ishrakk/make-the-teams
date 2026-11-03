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
  4. Make RESTARTS attempts and keep the best result.

The random starts are also why "reshuffle" works: equally good splits exist,
and a different seed usually lands on a different one.
"""

from __future__ import annotations

import random
import secrets
from collections.abc import Iterable

from app.splitter.cost import DEFAULT_WEIGHTS, Weights, score
from app.splitter.models import Assignment, Player, Position, SplitResult

# Measured by benchmark.py; see "How good is the search?" in README.md.
RESTARTS = 150

_DISPLAY_ORDER = {position: index for index, position in enumerate(Position)}


class _State:
    """One candidate split, with position counts kept up to date for fast scoring."""

    def __init__(self, players: list[Player], team_of: list[int], weights: Weights):
        self.players = players
        self.team_of = team_of
        self.position_of = [player.primary for player in players]
        self.weights = weights
        self.off_position = 0
        self.counts = [{position: 0 for position in Position} for _ in range(2)]
        for team, position in zip(team_of, self.position_of, strict=True):
            self.counts[team][position] += 1

    def cost(self) -> float:
        return score(self.counts[0], self.counts[1], self.off_position, self.weights).total

    def swap(self, i: int, j: int) -> None:
        """Exchange the teams of players i and j. Calling it twice undoes it."""
        team_i, team_j = self.team_of[i], self.team_of[j]
        position_i, position_j = self.position_of[i], self.position_of[j]
        self.counts[team_i][position_i] -= 1
        self.counts[team_j][position_i] += 1
        self.counts[team_j][position_j] -= 1
        self.counts[team_i][position_j] += 1
        self.team_of[i], self.team_of[j] = team_j, team_i

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


def _sorted_team(assignments: list[Assignment]) -> tuple[Assignment, ...]:
    return tuple(
        sorted(assignments, key=lambda a: (_DISPLAY_ORDER[a.position], a.player.name.lower()))
    )


def _warnings(team_a: tuple[Assignment, ...], team_b: tuple[Assignment, ...]) -> tuple[str, ...]:
    """Problems the organiser should know about, in plain words."""
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
    best_cost = float("inf")
    best_state: _State | None = None
    for attempt in range(RESTARTS):
        team_of = [index % 2 for index in range(n)]  # Team A gets the extra player if n is odd.
        rng.shuffle(team_of)
        state = _State(roster, team_of, weights)
        if attempt % 2:
            for index, player in enumerate(roster):
                if player.secondary and rng.random() < 0.5:
                    state.toggle_position(index)
        cost = _climb(state, rng)
        if cost < best_cost:
            best_cost, best_state = cost, state

    teams: list[list[Assignment]] = [[], []]
    for index, player in enumerate(roster):
        teams[best_state.team_of[index]].append(Assignment(player, best_state.position_of[index]))
    team_a, team_b = _sorted_team(teams[0]), _sorted_team(teams[1])

    return SplitResult(
        team_a=team_a,
        team_b=team_b,
        seed=seed,
        cost=score(best_state.counts[0], best_state.counts[1], best_state.off_position, weights),
        warnings=_warnings(team_a, team_b),
    )
