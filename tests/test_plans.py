"""Tests for what free and paid groups get, and for changing a plan."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import Group, Rating
from app.errors import UserError
from app.games import service as games
from app.groups import service as groups
from app.ratings import service as ratings
from tests.conftest import RATING_SECRET


def free_group(site):
    admin, group = site.group_with_admin(plan="free")
    member = site.member(admin, group, "m@example.com")
    return admin, group, member


def run_command(database_url, *args):
    return subprocess.run(
        [sys.executable, "-m", "app.groups", *args],
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": database_url},
    )


def test_new_groups_start_on_the_free_plan(site, db):
    browser = site.person("a@example.com")
    browser.post(
        "/groups",
        data={
            "name": "New",
            "weekday": "5",
            "timezone": "America/New_York",
            "player_name": "A",
            "primary": "MID",
        },
    )
    db.expire_all()
    assert db.scalars(select(Group)).one().plan == "free"


def test_database_rejects_an_unknown_plan(db):
    db.add(Group(name="X", join_code="X" * 12, game_weekday=1, timezone="UTC", plan="gold"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_free_groups_see_an_explanation_instead_of_the_rating_form(site):
    _, _, member = free_group(site)
    page = member.get("/ratings").text
    assert "part of the paid plan" in page
    assert 'type="radio"' not in page


def test_free_groups_cannot_save_ratings_by_posting_directly(site, db):
    admin, group, member = free_group(site)
    target = site.player(group, "admin")
    member.post("/ratings", data={f"score_{target.id}": "5"})
    db.expire_all()
    assert list(db.scalars(select(Rating))) == []
    assert "part of the paid plan" in member.get("/ratings").text


def test_paid_groups_get_the_rating_form(site):
    admin, group = site.group_with_admin(plan="paid")
    member = site.member(admin, group, "m@example.com")
    assert 'type="radio"' in member.get("/ratings").text


def make_rated_group(site, db, plan_when_teams_made):
    """A paid group with ratings, optionally moved to free before teams are made."""
    admin, group = site.group_with_admin(plan="paid")
    people = [admin]
    for name in ("a", "b", "c", "d"):
        people.append(site.member(admin, group, f"{name}@example.com"))
    names = ["admin", "a", "b", "c", "d"]
    players = {name: site.player(group, name) for name in names}
    for rater_name, rater in zip(names, people, strict=True):
        rater.post(
            "/ratings",
            data={
                f"score_{player.id}": "4" for name, player in players.items() if name != rater_name
            },
        )
        rater.post("/attendance", data={"status": "in"})
    db.expire_all()
    group = db.get(Group, group.id)
    groups.set_plan(db, group, plan_when_teams_made)
    admin.post("/teams")
    db.expire_all()
    return admin, people[1], group


def test_paid_groups_are_balanced_on_ratings(site, db):
    admin, member, group = make_rated_group(site, db, "paid")
    teams = games.game_view(db, group, games.current_game(db, group)).teams
    assert teams.explanation.a.average is not None
    page = admin.get("/").text
    assert "Team score" in page and "Individual ratings" in page


def test_free_groups_are_not_balanced_on_ratings_even_if_ratings_exist(site, db):
    admin, member, group = make_rated_group(site, db, "free")
    teams = games.game_view(db, group, games.current_game(db, group)).teams
    assert all(player.rating is None for player in teams.a + teams.b)
    page = admin.get("/").text
    assert "Why these teams" in page
    assert "Skill balancing is on the paid plan." in page
    assert "Team score" not in page and "Individual ratings" not in page


def test_admins_of_free_groups_see_their_plan_and_no_rating_averages(site, db):
    admin, member, group = make_rated_group(site, db, "free")
    page = admin.get("/group/configure").text
    assert "Plan: Free" in page
    assert "Rating 4.0" not in page and "Fewer than" not in page


def test_moving_to_free_keeps_ratings_and_moving_back_restores_them(site, db):
    admin, _, group = make_rated_group(site, db, "free")
    assert db.scalars(select(Rating)).first() is not None
    groups.set_plan(db, group, "paid")
    page = admin.get("/group/configure").text
    assert "Plan: Paid" in page and "Rating 4.0 from 4 people" in page


def test_service_refuses_ratings_for_free_groups(site, db):
    _, group, _ = free_group(site)
    rater = site.player(group, "m")
    other = site.player(group, "admin")
    with pytest.raises(UserError, match="paid plan"):
        ratings.save_ratings(db, RATING_SECRET, rater, {other.id: 3})


def test_set_plan_rejects_an_unknown_plan(site, db):
    _, group, _ = free_group(site)
    with pytest.raises(UserError, match="must be one of"):
        groups.set_plan(db, group, "gold")


def test_members_cannot_change_a_plan_from_the_site(site, db):
    admin, group, member = free_group(site)
    for browser in (admin, member):
        assert browser.post("/group/plan", data={"plan": "paid"}).status_code in (404, 405)
    db.expire_all()
    assert db.get(Group, group.id).plan == "free"


def test_command_lists_groups_and_changes_a_plan(site, db, database_url):
    _, group, _ = free_group(site)
    listing = run_command(database_url, "list")
    assert listing.returncode == 0
    assert "free" in listing.stdout and "Saturday Crew" in listing.stdout
    assert groups.format_code(group.join_code) in listing.stdout

    changed = run_command(database_url, "set-plan", groups.format_code(group.join_code), "paid")
    assert changed.returncode == 0
    assert "Saturday Crew is now on the paid plan." in changed.stdout
    db.expire_all()
    assert db.get(Group, group.id).plan == "paid"


def test_command_rejects_a_wrong_code_and_plan(site, database_url):
    _, group, _ = free_group(site)
    wrong_code = run_command(database_url, "set-plan", "WRONGCODE", "paid")
    assert wrong_code.returncode != 0 and "No group has that code" in wrong_code.stderr
    wrong_plan = run_command(database_url, "set-plan", group.join_code, "gold")
    assert wrong_plan.returncode != 0
