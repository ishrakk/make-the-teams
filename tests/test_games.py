"""Tests for the game rules, against a real database."""

from __future__ import annotations

from datetime import date
from urllib.parse import unquote

import pytest
from sqlalchemy.exc import IntegrityError

from app.db.models import Player
from app.games import service
from app.games.service import GameError

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


def squad(db, count=12):
    players = [service.add_player(db, "Keeper A", "GK"), service.add_player(db, "Keeper B", "GK")]
    for index in range(count - 2):
        players.append(service.add_player(db, f"Player {index}", ("DEF", "MID", "FWD")[index % 3]))
    return players


def test_names_are_unique_ignoring_case_and_spacing(db):
    service.add_player(db, "Sam Lee", "MID")
    with pytest.raises(GameError, match="already on the list"):
        service.add_player(db, "  sam   lee ", "FWD")


def test_database_rejects_duplicate_names_on_its_own(db):
    db.add(Player(name="Sam", primary_position="MID"))
    db.commit()
    db.add(Player(name="SAM", primary_position="MID"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_database_rejects_an_invalid_position(db):
    db.add(Player(name="Sam", primary_position="XXX"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


@pytest.mark.parametrize(
    ("name", "primary", "secondary", "message"),
    [
        ("", "MID", "", "Enter a name"),
        ("x" * 61, "MID", "", "up to 60"),
        ("Sam", "", "", "main position"),
        ("Sam", "MID", "MID", "must differ"),
        ("Sam", "MID", "NOPE", "valid second"),
    ],
)
def test_invalid_player_details_are_rejected(db, name, primary, secondary, message):
    with pytest.raises(GameError, match=message):
        service.add_player(db, name, primary, secondary)


def test_removed_player_can_be_added_back(db):
    player = service.add_player(db, "Sam", "MID")
    service.remove_player(db, player.id)
    assert service.active_players(db) == []
    back = service.add_player(db, "Sam", "FWD")
    assert back.id == player.id
    assert back.primary_position == "FWD"


def test_cannot_rename_a_player_to_a_taken_name(db):
    service.add_player(db, "Sam", "MID")
    other = service.add_player(db, "Alex", "MID")
    with pytest.raises(GameError, match="already taken"):
        service.update_player(db, other.id, "sam", "MID")


def test_get_or_create_game_returns_the_same_game(db):
    assert (
        service.get_or_create_game(db, SATURDAY).id == service.get_or_create_game(db, SATURDAY).id
    )


def test_changing_an_rsvp_replaces_the_old_answer(db):
    game = service.get_or_create_game(db, SATURDAY)
    player = service.add_player(db, "Sam", "MID")
    service.set_rsvp(db, game, player.id, "in")
    service.set_rsvp(db, game, player.id, "out")
    view = service.game_view(db, game)
    assert view.going == []
    assert [p.name for p in view.not_going] == ["Sam"]


def test_players_who_have_not_answered_are_listed(db):
    game = service.get_or_create_game(db, SATURDAY)
    sam = service.add_player(db, "Sam", "MID")
    service.add_player(db, "Alex", "MID")
    service.set_rsvp(db, game, sam.id, "in")
    assert [p.name for p in service.game_view(db, game).no_answer] == ["Alex"]


def test_removed_players_drop_out_of_the_game(db):
    game = service.get_or_create_game(db, SATURDAY)
    sam = service.add_player(db, "Sam", "MID")
    service.set_rsvp(db, game, sam.id, "in")
    service.remove_player(db, sam.id)
    assert service.game_view(db, game).going == []


def test_make_teams_includes_only_players_who_are_in(db):
    game = service.get_or_create_game(db, SATURDAY)
    players = squad(db)
    for player in players[:10]:
        service.set_rsvp(db, game, player.id, "in")
    service.set_rsvp(db, game, players[10].id, "out")
    service.make_teams(db, game, seed=1)
    teams = service.game_view(db, game).teams
    names = {member.name for member in teams.a + teams.b}
    assert names == {player.name for player in players[:10]}
    assert len(teams.a) == len(teams.b) == 5
    assert not teams.is_out_of_date


def test_making_teams_again_replaces_the_old_teams(db):
    game = service.get_or_create_game(db, SATURDAY)
    for player in squad(db):
        service.set_rsvp(db, game, player.id, "in")
    service.make_teams(db, game, seed=1)
    service.make_teams(db, game, seed=2)
    view = service.game_view(db, game)
    assert view.teams.seed == 2
    assert len(view.teams.a) + len(view.teams.b) == 12


def test_stored_teams_match_the_seed(db):
    game = service.get_or_create_game(db, SATURDAY)
    for player in squad(db):
        service.set_rsvp(db, game, player.id, "in")
    service.make_teams(db, game, seed=5)
    first = service.game_view(db, game).teams
    service.make_teams(db, game, seed=5)
    assert service.game_view(db, game).teams.a == first.a


def test_teams_are_flagged_when_the_list_changes(db):
    game = service.get_or_create_game(db, SATURDAY)
    players = squad(db)
    for player in players:
        service.set_rsvp(db, game, player.id, "in")
    service.make_teams(db, game, seed=1)
    service.set_rsvp(db, game, players[0].id, "out")
    assert service.game_view(db, game).teams.is_out_of_date


def test_cannot_make_teams_with_too_few_players(db):
    game = service.get_or_create_game(db, SATURDAY)
    service.set_rsvp(db, game, service.add_player(db, "Sam", "MID").id, "in")
    with pytest.raises(GameError, match="at least 2"):
        service.make_teams(db, game)


def test_share_link_contains_both_teams(db):
    game = service.get_or_create_game(db, SATURDAY)
    for player in squad(db):
        service.set_rsvp(db, game, player.id, "in")
    service.make_teams(db, game, seed=1)
    text = unquote(service.game_view(db, game).teams.share_url)
    assert "Saturday 7 November" in text
    assert "Team A" in text and "Team B" in text
    assert "GK Keeper A" in text
