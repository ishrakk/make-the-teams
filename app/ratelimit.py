"""Attempt limits, counted per fixed time window and stored in the database."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import RateLimit

SITEWIDE = "all"
MINUTE = 60
HOUR = 60 * MINUTE
DAY = 24 * HOUR


@dataclass(frozen=True)
class Limit:
    name: str
    max_count: int
    window_seconds: int


WRONG_CODE_PER_VISITOR = Limit("wrong-code", 10, 15 * MINUTE)
WRONG_PASSWORD_PER_VISITOR = Limit("wrong-password", 30, 15 * MINUTE)
WRONG_PASSWORD_PER_EMAIL = Limit("wrong-password-email", 10, 15 * MINUTE)
SIGNUP_PER_VISITOR = Limit("signup", 10, DAY)
RESET_PER_VISITOR = Limit("reset", 10, HOUR)
RESET_PER_EMAIL = Limit("reset-email", 3, HOUR)
GROUPS_PER_VISITOR = Limit("create", 5, DAY)
GROUPS_SITEWIDE = Limit("create-all", 500, DAY)


def _bucket(limit: Limit) -> int:
    return int(time.time()) // limit.window_seconds


def _key(limit: Limit, subject: str) -> str:
    return f"{limit.name}:{subject}"[:80]


def is_blocked(db: Session, limit: Limit, subject: str = SITEWIDE) -> bool:
    count = db.scalar(
        select(RateLimit.count).where(
            RateLimit.key == _key(limit, subject), RateLimit.bucket == _bucket(limit)
        )
    )
    return count is not None and count >= limit.max_count


def record(db: Session, limit: Limit, subject: str = SITEWIDE) -> None:
    """Count one attempt, and clear out counts from windows that have ended."""
    now = datetime.now(UTC)
    db.execute(delete(RateLimit).where(RateLimit.expires_at < now))
    statement = insert(RateLimit).values(
        key=_key(limit, subject),
        bucket=_bucket(limit),
        count=1,
        expires_at=now + timedelta(seconds=limit.window_seconds),
    )
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[RateLimit.key, RateLimit.bucket],
            set_={"count": RateLimit.count + 1},
        )
    )
    db.commit()
