"""Tests that test users work locally and can't exist in a real deployment."""

from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app.db.models import Group, Player, Rating, User
from app.demo import seed
from app.web.main import create_app
from tests.conftest import RATING_SECRET, Site, make_settings


@pytest.fixture
def demo_site(db, database_url) -> Site:
    return Site(create_app(make_settings(database_url, demo_mode=True)), db)


def demo_user(db, name: str) -> User:
    return db.scalars(select(User).where(User.email == f"{name}@{seed.DEMO_EMAIL_DOMAIN}")).one()


def test_demo_mode_refuses_to_start_with_secure_cookies(database_url):
    with pytest.raises(ValidationError, match="local testing"):
        make_settings(database_url, demo_mode=True, secure_cookies=True)


def test_demo_routes_do_not_exist_without_demo_mode(site):
    browser = site.browser()
    assert browser.get("/demo").status_code == 404
    assert browser.post("/demo/switch/1").status_code == 404
    assert "Test mode" not in browser.get("/").text


def test_seeding_refuses_without_demo_mode(database_url):
    result = subprocess.run(
        [sys.executable, "-m", "app.demo"],
        capture_output=True,
        text=True,
        env={
            "DATABASE_URL": database_url,
            "SESSION_SECRET": "s" * 32,
            "RATING_SECRET": "r" * 32,
            "PUBLIC_URL": "https://teams.test",
        },
    )
    assert result.returncode != 0
    assert "only for local testing" in result.stderr


def test_seed_creates_groups_players_votes_and_ratings(demo_site, db):
    seed.seed(db, RATING_SECRET)
    assert db.scalar(select(func.count()).select_from(Group)) == 2
    assert db.scalar(select(func.count()).select_from(User)) == len(seed.PLAYERS) + 1
    assert db.scalar(select(func.count()).select_from(Rating)) == 14 * 13
    saturday = db.scalars(select(Group).where(Group.name == "Saturday Crew")).one()
    statuses = db.scalars(select(Player.status).where(Player.group_id == saturday.id)).all()
    assert statuses.count("approved") == 14 and statuses.count("pending") == 1


def test_seed_is_detected_and_reset_only_removes_test_data(demo_site, db):
    _, real_group = demo_site.group_with_admin("real@example.com", "Real Group")
    seed.seed(db, RATING_SECRET)
    assert seed.has_demo_data(db)
    seed.reset(db)
    assert not seed.has_demo_data(db)
    assert [g.name for g in db.scalars(select(Group))] == ["Real Group"]
    assert [u.email for u in db.scalars(select(User))] == ["real@example.com"]


def test_switching_users_changes_who_you_are(demo_site, db):
    seed.seed(db, RATING_SECRET)
    browser = demo_site.browser()
    page = browser.get("/demo").text
    assert "Adam" in page and "Saturday Crew: admin" in page and "waiting for approval" in page

    browser.post(f"/demo/switch/{demo_user(db, 'adam').id}")
    assert "Reshuffle" not in browser.get("/").text
    assert "Make teams from" in browser.get("/").text
    assert "Test mode: adam@example.test" in browser.get("/").text

    browser.post(f"/demo/switch/{demo_user(db, 'liam').id}")
    page = browser.get("/").text
    assert "Are you coming, Liam?" in page and "Make teams from" not in page


def test_a_pending_test_user_sees_only_the_waiting_message(demo_site, db):
    seed.seed(db, RATING_SECRET)
    browser = demo_site.browser()
    browser.post(f"/demo/switch/{demo_user(db, 'omar').id}")
    assert browser.get("/").headers["location"] == "/groups"
    assert "Waiting for an admin to approve you" in browser.get("/groups").text


def test_test_users_can_log_in_with_the_shared_password(demo_site, db):
    seed.seed(db, RATING_SECRET)
    browser = demo_site.browser()
    browser.post(
        "/login", data={"email": f"adam@{seed.DEMO_EMAIL_DOMAIN}", "password": seed.DEMO_PASSWORD}
    )
    assert browser.get("/account").status_code == 200


def test_real_accounts_cannot_be_switched_to_even_in_demo_mode(demo_site, db):
    demo_site.person("real@example.com")
    real = db.scalars(select(User).where(User.email == "real@example.com")).one()
    browser = demo_site.browser()
    assert browser.post(f"/demo/switch/{real.id}").status_code == 404
    assert browser.get("/account").status_code == 303
