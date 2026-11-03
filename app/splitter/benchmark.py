"""Check how close the search gets to the true best cost.

    python -m app.splitter.benchmark

Re-run this after changing the weights or the search. The cost currently depends
only on how many players each team has per position when nobody is rated, so the
exact best cost can be calculated by trying every combination of counts. Ratings
make players different from each other, which rules this out. For them, this
compares 150 attempts with 3,000 on the same rosters.
"""

from __future__ import annotations

import random
import time
from dataclasses import replace

from app.splitter import DEFAULT_WEIGHTS, Player, Position, Weights, search, split_teams
from app.splitter.cost import score

POSITIONS = list(Position)
ROSTER_SIZES = (14, 18, 22, 26, 30)
ROSTERS_PER_SIZE = 30
RATED_ROSTERS_PER_SIZE = 8
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
                    team_a = dict(zip(POSITIONS, a, strict=True))
                    team_b = dict(
                        zip(POSITIONS, (t - c for t, c in zip(total, a, strict=True)), strict=True)
                    )
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
                cost = split_teams(players, seed=number, tolerance=0).cost.total
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


def rated_comparison() -> None:
    """Measure the cost of stopping at the usual number of attempts."""
    print()
    print(
        f"{'players':>7} {'rosters':>8} {'avg gap':>9} {'worst gap':>10} {'worst rating gap':>17}"
    )
    for size in (14, 18, 22, 26):
        gaps = []
        rating_gaps = []
        for number in range(RATED_ROSTERS_PER_SIZE):
            rng = random.Random(f"rated-{size}-{number}")
            players = [
                replace(player, rating=round(rng.uniform(1.5, 5), 1))
                for player in random_roster(rng, size, 0.5)
            ]
            usual = split_teams(players, seed=number, tolerance=0)
            default_restarts = search.RESTARTS
            search.RESTARTS = 3000
            thorough = split_teams(players, seed=number + 1, tolerance=0)
            search.RESTARTS = default_restarts
            gaps.append(max(0.0, usual.cost.total - thorough.cost.total))
            rating_gaps.append(_average_gap(usual))
        print(
            f"{size:>7} {RATED_ROSTERS_PER_SIZE:>8} {sum(gaps) / len(gaps):>9.3f} "
            f"{max(gaps):>10.3f} {max(rating_gaps):>17.3f}",
            flush=True,
        )


def _average_gap(result) -> float:
    def average(team) -> float:
        return sum(a.player.rating for a in team) / len(team)

    return abs(average(result.team_a) - average(result.team_b))


if __name__ == "__main__":
    main()
    rated_comparison()
