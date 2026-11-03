"""Tests for the rules the splitter must keep, whatever the weights are."""

from __future__ import annotations

import itertools
import random
from collections import Counter

import pytest

from app.splitter import DEFAULT_WEIGHTS, Player, Position, split_teams
from app.splitter.cost import score
from app.splitter.search import _relative_skill

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
    skill = _relative_skill(sorted(players, key=lambda p: str(p.id)))
    by_id = sorted(players, key=lambda p: str(p.id))
    players = by_id
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
            advantage = sum(skill[i] if i in members else -skill[i] for i in range(n))
            best = min(best, score(counts[0], counts[1], off, DEFAULT_WEIGHTS, advantage).total)
    return best


@pytest.mark.parametrize("seed", range(40))
def test_search_finds_the_true_best_cost_on_small_rosters(seed):
    rng = random.Random(seed)
    players = random_roster(rng, rng.choice([6, 7, 8, 9, 10]))
    result = split_teams(players, seed=seed, tolerance=0)
    assert result.cost.total == pytest.approx(brute_force_best(players))


@pytest.mark.parametrize("seed", range(25))
def test_search_finds_the_true_best_cost_with_ratings(seed):
    rng = random.Random(1000 + seed)
    players = [
        Player(p.id, p.name, p.primary, p.secondary, round(rng.uniform(1, 5), 1))
        for p in random_roster(rng, rng.choice([6, 7, 8, 9]))
    ]
    result = split_teams(players, seed=seed, tolerance=0)
    assert result.cost.total == pytest.approx(brute_force_best(players))


def rated_midfielders(ratings) -> list[Player]:
    return [Player(i, f"P{i}", MID, None, rating) for i, rating in enumerate(ratings)]


def average(team) -> float:
    return sum(a.player.rating for a in team) / len(team)


def test_strong_players_are_spread_across_teams():
    result = split_teams(rated_midfielders([5, 5, 5, 5, 1, 1, 1, 1]), seed=1)
    assert average(result.team_a) == pytest.approx(average(result.team_b))


def test_position_balance_outranks_a_small_skill_gap():
    players = [
        Player(0, "Keeper A", GK, None, 5.0),
        Player(1, "Keeper B", GK, None, 1.0),
        *[Player(i, f"P{i}", MID, None, 3.0) for i in range(2, 12)],
    ]
    result = split_teams(players, seed=1)
    assert positions(result.team_a)[GK] == positions(result.team_b)[GK] == 1


def test_unrated_players_count_as_average():
    players = [*rated_midfielders([5, 1]), Player(2, "New", MID), Player(3, "Also new", MID)]
    result = split_teams(players, seed=1, tolerance=0)
    # 5 and 1 average 3, the same as two unrated players, so any even split is fair.
    assert result.cost.skill_gap == pytest.approx(0)


def test_nobody_rated_means_no_skill_cost():
    assert split_teams(random_roster(random.Random(1), 12), seed=1).cost.skill_gap == 0


def test_short_team_is_not_penalized_for_a_lower_total():
    result = split_teams(rated_midfielders([3, 3, 3, 3, 3]), seed=1)
    assert result.cost.skill_gap == pytest.approx(0)


def test_reshuffle_varies_rated_teams_without_a_real_cost_increase():
    rng = random.Random(3)
    players = [
        Player(i, f"P{i}", (DEF, MID, FWD)[i % 3], None, round(rng.uniform(1, 5), 1))
        for i in range(18)
    ]
    results = [split_teams(players, seed=seed) for seed in range(10)]
    assert len({frozenset(a.player.id for a in r.team_a) for r in results}) >= 5
    best = split_teams(players, seed=0, tolerance=0).cost.total
    assert all(r.cost.total <= best + 1.5 for r in results)


def test_swap_keeps_the_rating_advantage_correct():
    from app.splitter.search import _State

    players = rated_midfielders([5, 1, 4, 2])
    skill = _relative_skill(players)
    state = _State(players, [0, 1, 0, 1], DEFAULT_WEIGHTS, skill)
    state.swap(0, 1)
    expected = sum(v if t == 0 else -v for t, v in zip(state.team_of, skill, strict=True))
    assert state.rating_advantage == pytest.approx(expected)
    state.swap(0, 1)
    assert state.rating_advantage == pytest.approx(2 + 2 + 1 + 1)
