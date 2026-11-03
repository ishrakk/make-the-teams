"""Shared setup. Database tests run against real PostgreSQL, using the real migrations."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.web.main import create_app

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
GROUP_PASSCODE = "group-code"
ADMIN_PASSCODE = "admin-code"


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
        connection.execute(text("TRUNCATE players, games RESTART IDENTITY CASCADE"))
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


@pytest.fixture
def client(db, database_url):
    settings = Settings(
        database_url=database_url,
        session_secret="x" * 32,
        group_passcode=GROUP_PASSCODE,
        admin_passcode=ADMIN_PASSCODE,
        secure_cookies=False,
        _env_file=None,
    )
    return TestClient(create_app(settings), follow_redirects=False)


@pytest.fixture
def member(client):
    client.post("/login", data={"passcode": GROUP_PASSCODE})
    return client


@pytest.fixture
def admin(client):
    client.post("/login", data={"passcode": ADMIN_PASSCODE})
    return client
