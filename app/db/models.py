"""Database tables. After changing this file, add a migration (see migrations/README.md)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

POSITION_VALUES = "('GK', 'DEF', 'MID', 'FWD')"


class Base(DeclarativeBase):
    # Predictable constraint names make migrations reliable.
    metadata = MetaData(
        naming_convention={
            "ix": "ix_%(column_0_label)s",
            "uq": "uq_%(table_name)s_%(column_0_name)s",
            "ck": "ck_%(table_name)s_%(constraint_name)s",
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
            "pk": "pk_%(table_name)s",
        }
    )


class User(Base):
    """An account. Passwords are stored only as Argon2 hashes."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)  # Always lowercase
    password_hash: Mapped[str] = mapped_column(String(255))
    # Raised when the password changes, which signs out every other device.
    session_epoch: Mapped[int] = mapped_column(Integer, server_default="0")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PasswordReset(Base):
    """A reset link in progress. Only a hash of the link's token is kept."""

    __tablename__ = "password_resets"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Group(Base):
    """A pickup group."""

    __tablename__ = "groups"
    __table_args__ = (CheckConstraint("game_weekday BETWEEN 0 AND 6", name="game_weekday_valid"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    join_code: Mapped[str] = mapped_column(String(12), unique=True)
    game_weekday: Mapped[int] = mapped_column(SmallInteger)  # Monday is 0, Saturday is 5
    timezone: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Player(Base):
    """A person in a group. One account can be in many groups, as one player in each."""

    __tablename__ = "players"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id"),
        # A removed player's name is free for someone else to use.
        Index(
            "uq_players_group_name_lower",
            "group_id",
            text("lower(name)"),
            unique=True,
            postgresql_where=text("status <> 'removed'"),
        ),
        CheckConstraint(f"primary_position IN {POSITION_VALUES}", name="primary_position_valid"),
        CheckConstraint(
            f"secondary_position IS NULL OR secondary_position IN {POSITION_VALUES}",
            name="secondary_position_valid",
        ),
        CheckConstraint("secondary_position <> primary_position", name="positions_differ"),
        CheckConstraint("role IN ('member', 'admin')", name="role_valid"),
        CheckConstraint("status IN ('pending', 'approved', 'removed')", name="status_valid"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(60))
    primary_position: Mapped[str] = mapped_column(String(3))
    secondary_position: Mapped[str | None] = mapped_column(String(3))
    role: Mapped[str] = mapped_column(String(6), server_default="member")
    status: Mapped[str] = mapped_column(String(8), server_default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (UniqueConstraint("group_id", "game_date"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    game_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Rsvp(Base):
    __tablename__ = "rsvps"
    __table_args__ = (CheckConstraint("status IN ('in', 'out')", name="status_valid"),)

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(String(3))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class TeamSplit(Base):
    """The latest teams for a game. Making teams again replaces them."""

    __tablename__ = "team_splits"

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    seed: Mapped[int] = mapped_column(BigInteger)
    cost_total: Mapped[float] = mapped_column(Float)
    warnings: Mapped[list[str]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class TeamAssignment(Base):
    __tablename__ = "team_assignments"
    __table_args__ = (
        CheckConstraint("team IN ('A', 'B')", name="team_valid"),
        CheckConstraint(f"position IN {POSITION_VALUES}", name="position_valid"),
    )

    game_id: Mapped[int] = mapped_column(
        ForeignKey("team_splits.game_id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    team: Mapped[str] = mapped_column(String(1))
    position: Mapped[str] = mapped_column(String(3))


class Rating(Base):
    """One anonymous score. See app/ratings/README.md for how the rater is hidden.

    There's deliberately no timestamp, because the time a score was saved could
    reveal who gave it.
    """

    __tablename__ = "ratings"
    __table_args__ = (CheckConstraint("score BETWEEN 1 AND 5", name="score_valid"),)

    rated_player_id: Mapped[int] = mapped_column(
        ForeignKey("players.id", ondelete="CASCADE"), primary_key=True
    )
    rater_tag: Mapped[str] = mapped_column(String(64), primary_key=True)
    score: Mapped[int] = mapped_column(SmallInteger)


class RateLimit(Base):
    """Attempt counts. In the database so that all web pods share them."""

    __tablename__ = "rate_limits"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    bucket: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    count: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
