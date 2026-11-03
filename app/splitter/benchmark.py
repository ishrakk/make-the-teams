"""Check how close the search gets to the true best cost.

    python -m app.splitter.benchmark

Re-run this after changing the weights or the search. The cost currently depends
only on how many players each team has per position, so the exact best cost can
be calculated by trying every combination of counts. If you add a term that
depends on individual players, such as ratings, optimal_cost() no longer applies.
"""

from __future__ import annotations

import random
import time

from app.splitter import DEFAULT_WEIGHTS, Player, Position, Weights, split_teams
from app.splitter.cost import score

POSITIONS = list(Position)
ROSTER_SIZES = (14, 18, 22, 26, 30)
ROSTERS_PER_SIZE = 30
SECONDARY_SHARES = (0.5, 1.0)  # share of players who list a secondary position


def optimal_cost(players: list[Player], weights: Weights = DEFAULT_WEIGHTS) -> float:
    # Fewest off-position players needed to reach each possible total per position.
    totals: dict[tuple[int, ...], int] = {(0, 0, 0, 0): 0}
    for player in players:
        reachable: dict[tuple[int, ...], int] = {}
        options = [(player.primary, 0)]
        if player.secondary:
            options.append((player.secondary, 1))
        for total, off in totals.items():
            for position, extra in options:
                index = POSITIONS.index(position)
                new = total[:index] + (total[index] + 1,) + total[index + 1 :]
                reachable[new] = min(reachable.get(new, len(players) + 1), off + extra)
        totals = reachable

    # For each total, try every way of giving Team A its share of the players.
    team_a_size = (len(players) + 1) // 2
    best = float("inf")
    for total, off in totals.items():
        for gk in range(min(total[0], team_a_size) + 1):
            for defenders in range(min(total[1], team_a_size - gk) + 1):
                for mids in range(min(total[2], team_a_size - gk - defenders) + 1):
                    fwds = team_a_size - gk - defenders - mids
                    if fwds > total[3]:
                        continue
                    a = (gk, defenders, mids, fwds)
                    team_a = dict(zip(POSITIONS, a))
                    team_b = dict(zip(POSITIONS, (t - c for t, c in zip(total, a))))
                    best = min(best, score(team_a, team_b, off, weights).total)
    return best


def random_roster(rng: random.Random, size: int, secondary_share: float) -> list[Player]:
    players = []
    for index in range(size):
        primary = rng.choice(POSITIONS)
        others = [position for position in POSITIONS if position != primary]
        secondary = rng.choice(others) if rng.random() < secondary_share else None
        players.append(Player(index, f"P{index}", primary, secondary))
    return players


def main() -> None:
    print(
        f"{'players':>7} {'with 2nd':>9} {'rosters':>8} {'missed best':>11} "
        f"{'worst gap':>10} {'slowest':>9}"
    )
    for size in ROSTER_SIZES:
        for share in SECONDARY_SHARES:
            missed = 0
            worst_gap = 0.0
            slowest = 0.0
            for number in range(ROSTERS_PER_SIZE):
                rng = random.Random(f"{size}-{share}-{number}")
                players = random_roster(rng, size, share)
                started = time.perf_counter()
                cost = split_teams(players, seed=number).cost.total
                slowest = max(slowest, time.perf_counter() - started)
                gap = cost - optimal_cost(players)
                if gap > 1e-9:
                    missed += 1
                    worst_gap = max(worst_gap, gap)
            print(
                f"{size:>7} {share:>9.0%} {ROSTERS_PER_SIZE:>8} {missed:>11} "
                f"{worst_gap:>10.2f} {slowest:>8.2f}s",
                flush=True,
            )


if __name__ == "__main__":
    main()
