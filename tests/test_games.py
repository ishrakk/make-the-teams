"""Tests for attendance and teams, against a real database."""

from __future__ import annotations

from datetime import date
from urllib.parse import unquote

import pytest

from app.db.models import Group, Player, User
from app.errors import UserError
from app.games import service
from app.ratings import service as ratings
from tests.conftest import RATING_SECRET

SATURDAY = date(2026, 11, 7)


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        (date(2026, 11, 3), date(2026, 11, 7)),  # Tuesday
        (date(2026, 11, 7), date(2026, 11, 7)),  # the game day itself
        (date(2026, 11, 8), date(2026, 11, 14)),  # the day after
    ],
)
def test_next_game_date(today, expected):
    assert service.next_game_date(today, weekday=5) == expected


@pytest.fixture
def group(db) -> Group:
    group = Group(name="Crew", join_code="A" * 12, game_weekday=5, timezone="America/New_York")
    db.add(group)
    db.commit()
    return group


def add_players(db, group, positions) -> list[Player]:
    players = []
    for index, position in enumerate(positions):
        user = User(email=f"p{group.id}-{index}@example.com", password_hash="x")
        db.add(user)
        db.flush()
        player = Player(
            group_id=group.id,
            user_id=user.id,
            name=f"Player {index}",
            primary_position=position,
            status="approved",
        )
        db.add(player)
        players.append(player)
    db.commit()
    return players


def squad(db, group, count=12) -> list[Player]:
    outfield = [("DEF", "MID", "FWD")[index % 3] for index in range(count - 2)]
    return add_players(db, group, ["GK", "GK", *outfield])


def all_in(db, game, players):
    for player in players:
        service.set_attendance(db, game, player, "in")


def test_each_group_has_its_own_game_for_a_date(db, group):
    other = Group(name="Other", join_code="B" * 12, game_weekday=5, timezone="America/New_York")
    db.add(other)
    db.commit()
    first = service.get_or_create_game(db, group, SATURDAY)
    assert service.get_or_create_game(db, group, SATURDAY).id == first.id
    assert service.get_or_create_game(db, other, SATURDAY).id != first.id


def test_changing_attendance_replaces_the_old_answer(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    [player] = add_players(db, group, ["MID"])
    service.set_attendance(db, game, player, "in")
    service.set_attendance(db, game, player, "out")
    view = service.game_view(db, group, game)
    assert view.going == []
    assert view.not_going == [player]


def test_invalid_attendance_is_rejected(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    [player] = add_players(db, group, ["MID"])
    with pytest.raises(UserError):
        service.set_attendance(db, game, player, "maybe")


def test_players_who_have_not_answered_are_listed(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    first, second = add_players(db, group, ["MID", "MID"])
    service.set_attendance(db, game, first, "in")
    assert service.game_view(db, group, game).no_answer == [second]


def test_removed_players_drop_out_of_the_game(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    [player] = add_players(db, group, ["MID"])
    service.set_attendance(db, game, player, "in")
    player.status = "removed"
    db.commit()
    assert service.game_view(db, group, game).going == []


def test_make_teams_includes_only_players_who_are_in(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    players = squad(db, group)
    all_in(db, game, players[:10])
    service.set_attendance(db, game, players[10], "out")
    service.make_teams(db, game, seed=1)
    teams = service.game_view(db, group, game).teams
    assert {m.name for m in teams.a + teams.b} == {p.name for p in players[:10]}
    assert len(teams.a) == len(teams.b) == 5
    assert not teams.is_out_of_date


def test_making_teams_again_replaces_the_old_teams(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    all_in(db, game, squad(db, group))
    service.make_teams(db, game, seed=1)
    service.make_teams(db, game, seed=2)
    teams = service.game_view(db, group, game).teams
    assert teams.seed == 2
    assert len(teams.a) + len(teams.b) == 12


def test_teams_are_flagged_when_the_list_changes(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    players = squad(db, group)
    all_in(db, game, players)
    service.make_teams(db, game, seed=1)
    service.set_attendance(db, game, players[0], "out")
    assert service.game_view(db, group, game).teams.is_out_of_date


def test_cannot_make_teams_with_too_few_players(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    all_in(db, game, add_players(db, group, ["MID"]))
    with pytest.raises(UserError, match="at least 2"):
        service.make_teams(db, game)


def test_ratings_balance_the_teams(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    players = add_players(db, group, ["MID"] * 8)
    raters = add_players_as_raters(db, group, 3)
    # Four strong players and four weak ones.
    for rater in raters:
        scores = {player.id: (5 if i < 4 else 1) for i, player in enumerate(players)}
        ratings.save_ratings(db, RATING_SECRET, rater, scores)
    all_in(db, game, players)
    service.make_teams(db, game, seed=1)
    teams = service.game_view(db, group, game).teams
    strong = {player.name for player in players[:4]}
    assert sum(m.name in strong for m in teams.a) == 2
    assert sum(m.name in strong for m in teams.b) == 2


def test_fewer_than_the_minimum_ratings_do_not_affect_teams(db, group):
    players = add_players(db, group, ["MID"] * 2)
    raters = add_players_as_raters(db, group, ratings.MIN_RATINGS - 1)
    for rater in raters:
        ratings.save_ratings(db, RATING_SECRET, rater, {players[0].id: 5})
    assert ratings.averages(db, [players[0].id]) == {}


def add_players_as_raters(db, group, count) -> list[Player]:
    players = []
    for index in range(count):
        user = User(email=f"rater{index}@example.com", password_hash="x")
        db.add(user)
        db.flush()
        player = Player(
            group_id=group.id,
            user_id=user.id,
            name=f"Rater {index}",
            primary_position="MID",
            status="approved",
        )
        db.add(player)
        players.append(player)
    db.commit()
    return players


def test_share_link_contains_both_teams(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    all_in(db, game, squad(db, group))
    service.make_teams(db, game, seed=1)
    text = unquote(service.game_view(db, group, game).teams.share_url)
    assert "Saturday, November 7" in text
    assert "Team A" in text and "Team B" in text
    assert "GK Player 0" in text


def rate_everyone(db, group, players, raters, scores):
    for rater in raters:
        ratings.save_ratings(
            db,
            RATING_SECRET,
            rater,
            {player.id: score for player, score in zip(players, scores, strict=True)},
        )


def test_explanation_has_scores_lines_and_reasons(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    players = add_players(db, group, ["GK", "GK", "DEF", "DEF", "FWD", "FWD"])
    rate_everyone(db, group, players, add_players_as_raters(db, group, 3), [3, 3, 4, 2, 4, 2])
    all_in(db, game, players)
    service.make_teams(db, game, seed=1)
    why = service.game_view(db, group, game).teams.explanation
    assert why.a.score + why.b.score == pytest.approx(18)
    assert why.a.average == pytest.approx(3) and why.b.average == pytest.approx(3)
    assert why.a.lines["GK"].count == 1 and why.b.lines["GK"].count == 1
    assert "Each team has one keeper." in why.reasons
    assert any("gap of 0.00" in reason for reason in why.reasons)
    assert why.total == pytest.approx(sum(value for _, value in why.factors))


def test_explanation_says_skill_was_not_used_without_ratings(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    all_in(db, game, add_players(db, group, ["MID"] * 4))
    service.make_teams(db, game, seed=1)
    why = service.game_view(db, group, game).teams.explanation
    assert why.a.score is None
    assert any("Skill wasn't used" in reason for reason in why.reasons)


def test_explanation_counts_unrated_players_as_average(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    players = add_players(db, group, ["MID"] * 4)
    rate_everyone(db, group, players[:2], add_players_as_raters(db, group, 3), [5, 1])
    all_in(db, game, players)
    service.make_teams(db, game, seed=1)
    why = service.game_view(db, group, game).teams.explanation
    assert why.a.score + why.b.score == pytest.approx(12)
    assert any("2 players with fewer than 3" in reason for reason in why.reasons)


def test_explanation_names_players_moved_to_their_second_position(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    players = add_players(db, group, ["GK", "GK", "DEF", "DEF", "DEF", "MID"])
    players[4].secondary_position = "MID"
    db.commit()
    all_in(db, game, players)
    service.make_teams(db, game, seed=1)
    why = service.game_view(db, group, game).teams.explanation
    assert any("Player 4 moved from defender to midfielder" in reason for reason in why.reasons)


def test_explanation_keeps_the_ratings_used_when_teams_were_made(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    players = add_players(db, group, ["MID"] * 2)
    raters = add_players_as_raters(db, group, 3)
    rate_everyone(db, group, players, raters, [5, 1])
    all_in(db, game, players)
    service.make_teams(db, game, seed=1)
    before = service.game_view(db, group, game).teams.explanation
    rate_everyone(db, group, players, raters, [1, 5])
    after = service.game_view(db, group, game).teams.explanation
    assert before == after


def test_teams_made_before_explanations_still_display(db, group):
    from app.db.models import TeamSplit

    game = service.get_or_create_game(db, group, SATURDAY)
    all_in(db, game, add_players(db, group, ["MID"] * 2))
    service.make_teams(db, game, seed=1)
    db.get(TeamSplit, game.id).cost_breakdown = None
    db.commit()
    teams = service.game_view(db, group, game).teams
    assert teams.explanation is None and len(teams.a) == 1


def strength_reasons(why) -> list[str]:
    return [reason for reason in why.reasons if "stronger" in reason]


def test_strengths_compare_lines_with_more_than_one_player_in_words(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    players = add_players(db, group, ["DEF"] * 4 + ["FWD"] * 4)
    raters = add_players_as_raters(db, group, 3)
    # Evenly matched overall, but one team must be stronger at the back.
    rate_everyone(db, group, players, raters, [5, 5, 1, 1, 1, 1, 5, 5])
    all_in(db, game, players)
    service.make_teams(db, game, seed=1)
    why = service.game_view(db, group, game).teams.explanation
    text = " ".join(strength_reasons(why))
    assert "defense" in text and "attack" in text
    assert not any(character.isdigit() for character in text)


def test_strengths_never_compare_one_player_with_one_player(db, group):
    game = service.get_or_create_game(db, group, SATURDAY)
    players = add_players(db, group, ["GK", "GK"])
    rate_everyone(db, group, players, add_players_as_raters(db, group, 3), [5, 1])
    all_in(db, game, players)
    service.make_teams(db, game, seed=1)
    assert strength_reasons(service.game_view(db, group, game).teams.explanation) == []
