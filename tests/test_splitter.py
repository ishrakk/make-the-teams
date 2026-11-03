"""Tests for the rules the splitter must keep, whatever the weights are."""

from __future__ import annotations

import itertools
import random
from collections import Counter

import pytest

from app.splitter import DEFAULT_WEIGHTS, Player, Position, split_teams
from app.splitter.cost import score

GK, DEF, MID, FWD = Position.GK, Position.DEF, Position.MID, Position.FWD


def roster(*specs: tuple[Position, Position | None]) -> list[Player]:
    return [Player(i, f"P{i}", primary, secondary) for i, (primary, secondary) in enumerate(specs)]


def positions(team) -> Counter:
    return Counter(a.position for a in team)


def random_roster(rng: random.Random, size: int) -> list[Player]:
    specs = []
    for _ in range(size):
        primary = rng.choice(list(Position))
        others = [position for position in Position if position != primary]
        specs.append((primary, rng.choice(others) if rng.random() < 0.5 else None))
    return roster(*specs)


@pytest.mark.parametrize("size", [2, 3, 10, 11, 22, 23, 30])
def test_team_sizes_never_differ_by_more_than_one_and_a_is_larger(size):
    result = split_teams(random_roster(random.Random(size), size), seed=1)
    assert len(result.team_a) + len(result.team_b) == size
    assert len(result.team_a) - len(result.team_b) in (0, 1)


def test_everyone_plays_exactly_once_on_a_position_they_accept():
    players = random_roster(random.Random(5), 22)
    result = split_teams(players, seed=1)
    assigned = result.team_a + result.team_b
    assert sorted(a.player.id for a in assigned) == sorted(p.id for p in players)
    for a in assigned:
        assert a.position in (a.player.primary, a.player.secondary)


def test_two_keepers_are_split_between_teams():
    players = roster((GK, None), (GK, None), *[(FWD, None)] * 10)
    result = split_teams(players, seed=3)
    assert positions(result.team_a)[GK] == 1
    assert positions(result.team_b)[GK] == 1


def test_each_position_is_split_evenly_when_counts_are_even():
    players = roster(*[(GK, None)] * 2, *[(DEF, None)] * 4, *[(MID, None)] * 4, *[(FWD, None)] * 2)
    result = split_teams(players, seed=4)
    assert positions(result.team_a) == positions(result.team_b)


def test_outfield_player_with_keeper_as_secondary_fills_in_for_a_missing_keeper():
    players = roster((GK, None), (DEF, GK), *[(FWD, None)] * 10)
    result = split_teams(players, seed=5)
    assert positions(result.team_a)[GK] == 1
    assert positions(result.team_b)[GK] == 1


def test_players_stay_on_primary_when_the_roster_is_already_balanced():
    players = roster(*[(GK, DEF)] * 2, *[(DEF, MID)] * 8, *[(MID, FWD)] * 6, *[(FWD, MID)] * 6)
    result = split_teams(players, seed=6)
    assert not [a for a in result.team_a + result.team_b if a.on_secondary]


def test_warns_when_a_team_has_no_keeper():
    result = split_teams(roster((GK, None), *[(FWD, None)] * 9), seed=1)
    assert any("no keeper" in warning for warning in result.warnings)


def test_warns_when_a_team_has_several_keepers():
    result = split_teams(roster(*[(GK, None)] * 3, *[(FWD, None)] * 7), seed=1)
    assert any("2 keepers" in warning for warning in result.warnings)


def test_warns_on_odd_player_count():
    result = split_teams(roster((GK, None), (GK, None), *[(MID, None)] * 9), seed=1)
    assert any("Odd number of players (11)" in warning for warning in result.warnings)


def test_same_seed_gives_the_same_teams_in_any_input_order():
    players = random_roster(random.Random(9), 20)
    first = split_teams(players, seed=42)
    second = split_teams(list(reversed(players)), seed=42)
    assert first.team_a == second.team_a and first.team_b == second.team_b


def test_different_seeds_produce_different_teams_without_getting_worse():
    players = roster(*[(GK, None)] * 2, *[(DEF, None)] * 8, *[(MID, None)] * 6, *[(FWD, None)] * 6)
    results = [split_teams(players, seed=seed) for seed in range(10)]
    distinct = {frozenset(a.player.id for a in result.team_a) for result in results}
    assert len(distinct) >= 5
    assert len({round(result.cost.total, 6) for result in results}) == 1


@pytest.mark.parametrize("players", [[], [Player(1, "Solo", MID)]])
def test_too_few_players_is_an_error(players):
    with pytest.raises(ValueError, match="at least 2"):
        split_teams(players)


def test_duplicate_player_is_an_error():
    with pytest.raises(ValueError, match="once"):
        split_teams([Player(1, "A", MID), Player(1, "A", MID)])


def brute_force_best(players: list[Player]) -> float:
    """Lowest possible cost, by checking every team split and position choice."""
    n = len(players)
    best = float("inf")
    options = [[p.primary] + ([p.secondary] if p.secondary else []) for p in players]
    for team_a in itertools.combinations(range(n), (n + 1) // 2):
        members = set(team_a)
        for choice in itertools.product(*options):
            counts = [{position: 0 for position in Position} for _ in range(2)]
            off = 0
            for index, position in enumerate(choice):
                counts[0 if index in members else 1][position] += 1
                off += position != players[index].primary
            best = min(best, score(counts[0], counts[1], off, DEFAULT_WEIGHTS).total)
    return best


@pytest.mark.parametrize("seed", range(40))
def test_search_finds_the_true_best_cost_on_small_rosters(seed):
    rng = random.Random(seed)
    players = random_roster(rng, rng.choice([6, 7, 8, 9, 10]))
    result = split_teams(players, seed=seed)
    assert result.cost.total == pytest.approx(brute_force_best(players))
