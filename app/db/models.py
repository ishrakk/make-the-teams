"""Database tables. After changing this file, add a migration (see migrations/README.md)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    MetaData,
    String,
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


class Player(Base):
    __tablename__ = "players"
    __table_args__ = (
        Index("uq_players_name_lower", text("lower(name)"), unique=True),
        CheckConstraint(f"primary_position IN {POSITION_VALUES}", name="primary_position_valid"),
        CheckConstraint(
            f"secondary_position IS NULL OR secondary_position IN {POSITION_VALUES}",
            name="secondary_position_valid",
        ),
        CheckConstraint("secondary_position <> primary_position", name="positions_differ"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    primary_position: Mapped[str] = mapped_column(String(3))
    secondary_position: Mapped[str | None] = mapped_column(String(3))
    active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Game(Base):
    __tablename__ = "games"

    id: Mapped[int] = mapped_column(primary_key=True)
    game_date: Mapped[date] = mapped_column(Date, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Rsvp(Base):
    __tablename__ = "rsvps"
    __table_args__ = (CheckConstraint("status IN ('in', 'out')", name="status_valid"),)

    game_id: Mapped[int] = mapped_column(
        ForeignKey("games.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
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
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), primary_key=True)
    team: Mapped[str] = mapped_column(String(1))
    position: Mapped[str] = mapped_column(String(3))
