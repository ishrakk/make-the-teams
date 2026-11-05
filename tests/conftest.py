"""Shared setup. Database tests run against real PostgreSQL, using the real migrations."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.models import Group, Player
from app.web.main import create_app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
PASSWORD = "correct-horse-battery"
RATING_SECRET = "r" * 32


@pytest.fixture(scope="session")
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("Set TEST_DATABASE_URL to run database tests.")
    # These tests wipe the database, so refuse anything not clearly meant for it.
    if "test" not in TEST_DATABASE_URL.rsplit("/", 1)[-1]:
        pytest.fail("TEST_DATABASE_URL must name a database containing 'test'.")
    engine = create_engine(TEST_DATABASE_URL)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        check=True,
        env={**os.environ, "DATABASE_URL": TEST_DATABASE_URL},
    )
    return TEST_DATABASE_URL


@pytest.fixture
def db(database_url):
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE users, groups, rate_limits RESTART IDENTITY CASCADE"))
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


class Site:
    """The running site. Each person gets a browser with their own cookies."""

    def __init__(self, app, db: Session):
        self.app = app
        self.db = db

    def browser(self) -> TestClient:
        return TestClient(self.app, follow_redirects=False)

    def person(self, email: str) -> TestClient:
        browser = self.browser()
        response = browser.post("/signup", data={"email": email, "password": PASSWORD})
        assert response.status_code == 303
        return browser

    def group_with_admin(
        self, email: str = "admin@example.com", name: str = "Saturday Crew", plan: str = "paid"
    ):
        browser = self.person(email)
        browser.post(
            "/groups",
            data={
                "name": name,
                "weekday": "5",
                "timezone": "America/New_York",
                "player_name": email.split("@")[0],
                "primary": "MID",
            },
        )
        self.db.expire_all()
        group = self.db.scalars(select(Group).where(Group.name == name)).one()
        group.plan = plan
        self.db.commit()
        return browser, group

    def ask_to_join(self, group: Group, email: str, primary: str = "MID") -> TestClient:
        browser = self.person(email)
        browser.post(
            f"/join/{group.join_code}",
            data={"name": email.split("@")[0], "primary": primary},
        )
        return browser

    def player(self, group: Group, name: str) -> Player:
        self.db.expire_all()
        return self.db.scalars(
            select(Player).where(Player.group_id == group.id, Player.name == name)
        ).one()

    def member(self, admin: TestClient, group: Group, email: str, primary: str = "MID"):
        browser = self.ask_to_join(group, email, primary)
        player = self.player(group, email.split("@")[0])
        admin.post(f"/group/requests/{player.id}/approve")
        return browser


def make_settings(database_url: str, **overrides) -> Settings:
    return Settings(
        **{
            "database_url": database_url,
            "session_secret": "s" * 32,
            "rating_secret": RATING_SECRET,
            "public_url": "https://teams.test",
            "secure_cookies": False,
            "log_emails": True,
            "email_from": "site@teams.test",
            **overrides,
        },
        _env_file=None,
    )


@pytest.fixture
def site(db, database_url) -> Site:
    return Site(create_app(make_settings(database_url)), db)
