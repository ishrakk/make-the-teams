"""Tests for what the site reports to Prometheus, and that it stays private."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from prometheus_client import generate_latest
from sqlalchemy import select

from app.db.models import User
from app.metrics.collector import DatabaseCollector
from tests.conftest import Site


def scrape(site: Site) -> str:
    metrics = site.app.state.metrics
    for collector in list(metrics.registry._collector_to_names):
        if isinstance(collector, DatabaseCollector):
            collector._cached_at = 0.0
    return generate_latest(metrics.registry).decode()


def value(text: str, name: str) -> float:
    for line in text.splitlines():
        if line.startswith(f"{name} "):
            return float(line.split()[-1])
    raise AssertionError(f"{name} not found")


def test_metrics_are_not_on_the_public_site(site):
    assert site.browser().get("/metrics").status_code == 404


def test_totals_count_users_groups_and_approved_players(site):
    admin, group = site.group_with_admin()
    site.member(admin, group, "m@example.com")
    site.ask_to_join(group, "waiting@example.com")
    text = scrape(site)
    assert value(text, "teams_users") == 3
    assert value(text, "teams_groups") == 1
    assert value(text, "teams_players_approved") == 2
    assert value(text, "teams_database_size_bytes") > 0


def test_active_users_are_counted_per_window(site, db):
    site.person("now@example.com").get("/account")
    site.person("yesterday@example.com")
    site.person("lastmonth@example.com")
    db.expire_all()
    users = {user.email: user for user in db.scalars(select(User))}
    now = datetime.now(UTC)
    users["yesterday@example.com"].last_seen_at = now - timedelta(hours=30)
    users["lastmonth@example.com"].last_seen_at = now - timedelta(days=30)
    db.commit()
    text = scrape(site)
    assert value(text, 'teams_active_users{window="15m"}') == 1
    assert value(text, 'teams_active_users{window="24h"}') == 1
    assert value(text, 'teams_active_users{window="7d"}') == 2


def test_last_seen_is_written_at_most_every_five_minutes(site, db):
    browser = site.person("a@example.com")
    browser.get("/account")
    db.expire_all()
    user = db.scalars(select(User)).one()
    first = user.last_seen_at
    assert first is not None
    browser.get("/account")
    db.expire_all()
    assert db.scalars(select(User)).one().last_seen_at == first

    user = db.scalars(select(User)).one()
    user.last_seen_at = datetime.now(UTC) - timedelta(minutes=6)
    db.commit()
    browser.get("/account")
    db.expire_all()
    assert db.scalars(select(User)).one().last_seen_at > first


def test_requests_are_labeled_by_route_so_codes_and_tokens_never_appear(site):
    _, group = site.group_with_admin()
    browser = site.browser()
    browser.get(f"/join/{group.join_code}")
    browser.get("/reset/secret-reset-token")
    browser.get("/no-such-page")
    browser.get("/static/style.css")
    browser.get("/")
    text = scrape(site)
    assert 'route="/",status="200"' in text
    assert 'route="/static",status="200"' in text
    assert group.join_code not in text
    assert "secret-reset-token" not in text
    assert 'route="/join/{code}"' in text
    assert 'route="/reset/{token}"' in text
    assert 'route="unmatched"' in text
    assert 'status="404"' in text


def test_uptime_metric_is_reported(site):
    assert value(scrape(site), "process_start_time_seconds") > 0


def test_a_database_failure_does_not_break_metrics(site, monkeypatch):
    metrics = site.app.state.metrics
    collector = next(
        c for c in metrics.registry._collector_to_names if isinstance(c, DatabaseCollector)
    )

    def fail():
        raise RuntimeError("database is down")

    collector._cached = []
    monkeypatch.setattr(collector, "_read", fail)
    assert "process_start_time_seconds" in generate_latest(metrics.registry).decode()
