"""Metrics: request counts from the web app, and totals read from the database."""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime, timedelta

from fastapi import Request
from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    ProcessCollector,
    start_http_server,
)
from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.db.models import Group, Player, User

logger = logging.getLogger(__name__)

CACHE_SECONDS = 30
ACTIVE_WINDOWS = {
    "15m": timedelta(minutes=15),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}


class DatabaseCollector(Collector):
    """Reads totals when Prometheus asks, at most once every 30 seconds."""

    def __init__(self, session_factory: sessionmaker[Session]):
        self.session_factory = session_factory
        self._cached_at = 0.0
        self._cached: list[GaugeMetricFamily] = []

    def _read(self) -> list[GaugeMetricFamily]:
        now = datetime.now(UTC)
        with self.session_factory() as db:
            users = GaugeMetricFamily("teams_users", "Accounts on the site")
            users.add_metric([], db.scalar(select(func.count()).select_from(User)))

            groups = GaugeMetricFamily("teams_groups", "Groups on the site")
            groups.add_metric([], db.scalar(select(func.count()).select_from(Group)))

            players = GaugeMetricFamily("teams_players_approved", "Approved players in all groups")
            players.add_metric(
                [],
                db.scalar(
                    select(func.count()).select_from(Player).where(Player.status == "approved")
                ),
            )

            active = GaugeMetricFamily(
                "teams_active_users", "Accounts seen recently", labels=["window"]
            )
            for label, window in ACTIVE_WINDOWS.items():
                count = db.scalar(
                    select(func.count()).select_from(User).where(User.last_seen_at >= now - window)
                )
                active.add_metric([label], count)

            size = GaugeMetricFamily("teams_database_size_bytes", "Size of the database")
            size.add_metric([], db.scalar(text("SELECT pg_database_size(current_database())")))
        return [users, groups, players, active, size]

    def collect(self):
        if time.monotonic() - self._cached_at > CACHE_SECONDS or not self._cached:
            try:
                self._cached = self._read()
                self._cached_at = time.monotonic()
            except Exception:
                # Metrics must never take the site down. Prometheus still gets process
                # metrics, and these simply go missing, which a dashboard shows as a gap.
                logger.exception("Couldn't read metrics from the database")
                return
        yield from self._cached


class Metrics:
    """One set of metrics for one app, kept separate so tests don't share counts."""

    def __init__(self, session_factory: sessionmaker[Session]):
        self.registry = CollectorRegistry()
        ProcessCollector(registry=self.registry)
        self.registry.register(DatabaseCollector(session_factory))
        self.requests = Counter(
            "teams_http_requests",
            "Requests handled",
            ["method", "route", "status"],
            registry=self.registry,
        )
        self.latency = Histogram(
            "teams_http_request_duration_seconds",
            "Time taken to handle a request",
            registry=self.registry,
        )

    def serve(self, port: int) -> None:
        start_http_server(port, registry=self.registry)

    def observe(self, request: Request, status: int, seconds: float) -> None:
        # Use the route's pattern, never the real URL. Real URLs contain group codes and
        # reset tokens, and each one would also create a new time series.
        route = request.scope.get("route")
        if route is not None:
            path = route.path
        elif request.url.path.startswith("/static/"):
            path = "/static"
        else:
            path = "unmatched"
        self.requests.labels(request.method, path, str(status)).inc()
        self.latency.observe(seconds)
