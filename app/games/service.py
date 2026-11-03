"""Operations on a group's games, attendance and teams.

The website calls these functions, and they connect the database to the splitter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Game, Group, Player, Rsvp, TeamAssignment, TeamSplit
from app.errors import UserError
from app.ratings import service as ratings
from app.splitter import Player as SplitterPlayer
from app.splitter import Position, split_teams

POSITION_LABELS = {
    "GK": "Goalkeeper",
    "DEF": "Defender",
    "MID": "Midfielder",
    "FWD": "Forward",
}
POSITION_ORDER = list(POSITION_LABELS)


def approved_players(db: Session, group: Group) -> list[Player]:
    query = (
        select(Player)
        .where(Player.group_id == group.id, Player.status == "approved")
        .order_by(func.lower(Player.name))
    )
    return list(db.scalars(query))


# Games and attendance


def next_game_date(today: date, weekday: int) -> date:
    """The next game day, which is today if today is a game day."""
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def get_or_create_game(db: Session, group: Group, game_date: date) -> Game:
    # ON CONFLICT handles two people opening the page for a new week at once.
    db.execute(insert(Game).values(group_id=group.id, game_date=game_date).on_conflict_do_nothing())
    db.commit()
    return db.scalars(
        select(Game).where(Game.group_id == group.id, Game.game_date == game_date)
    ).one()


def current_game(db: Session, group: Group) -> Game:
    """This group's next game, by the date where the group plays."""
    today = datetime.now(ZoneInfo(group.timezone)).date()
    return get_or_create_game(db, group, next_game_date(today, group.game_weekday))


def set_attendance(db: Session, game: Game, player: Player, status: str) -> None:
    """Record whether a player is coming. A new answer replaces the old one."""
    if status not in ("in", "out"):
        raise UserError("Choose in or out.")
    statement = insert(Rsvp).values(game_id=game.id, player_id=player.id, status=status)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[Rsvp.game_id, Rsvp.player_id],
            set_={"status": status, "updated_at": func.now()},
        )
    )
    db.commit()


# Teams


def make_teams(db: Session, game: Game, seed: int | None = None) -> None:
    """Make teams from the players who are in, replacing any earlier teams."""
    # Locking the game means two people pressing the button can't mix results.
    db.execute(select(Game.id).where(Game.id == game.id).with_for_update())
    players = _players_with_status(db, game, "in")
    averages = ratings.averages(db, [player.id for player in players])
    try:
        result = split_teams(
            [
                SplitterPlayer(
                    id=player.id,
                    name=player.name,
                    primary=Position(player.primary_position),
                    secondary=(
                        Position(player.secondary_position) if player.secondary_position else None
                    ),
                    rating=averages[player.id].value if player.id in averages else None,
                )
                for player in players
            ],
            seed=seed,
        )
    except ValueError as error:
        db.rollback()
        raise UserError(str(error)) from error

    db.execute(delete(TeamSplit).where(TeamSplit.game_id == game.id))
    db.add(
        TeamSplit(
            game_id=game.id,
            seed=result.seed,
            cost_total=result.cost.total,
            warnings=list(result.warnings),
        )
    )
    db.flush()
    for label, team in (("A", result.team_a), ("B", result.team_b)):
        for assignment in team:
            db.add(
                TeamAssignment(
                    game_id=game.id,
                    player_id=assignment.player.id,
                    team=label,
                    position=assignment.position.value,
                )
            )
    db.commit()


# What the game page shows


@dataclass(frozen=True)
class TeamMember:
    name: str
    position: str
    on_secondary: bool


@dataclass(frozen=True)
class Teams:
    a: list[TeamMember]
    b: list[TeamMember]
    warnings: list[str]
    seed: int
    is_out_of_date: bool  # The players who are in have changed since teams were made.
    share_url: str


@dataclass(frozen=True)
class GameView:
    game: Game
    going: list[Player]
    not_going: list[Player]
    no_answer: list[Player]
    teams: Teams | None

    def status_of(self, player: Player) -> str | None:
        if player in self.going:
            return "in"
        return "out" if player in self.not_going else None


def _players_with_status(db: Session, game: Game, status: str) -> list[Player]:
    query = (
        select(Player)
        .join(Rsvp, Rsvp.player_id == Player.id)
        .where(Rsvp.game_id == game.id, Rsvp.status == status, Player.status == "approved")
        .order_by(func.lower(Player.name))
    )
    return list(db.scalars(query))


def _share_text(game: Game, a: list[TeamMember], b: list[TeamMember]) -> str:
    lines = [format_game_date(game.game_date)]
    for label, team in (("Team A", a), ("Team B", b)):
        lines += ["", label] + [f"{member.position} {member.name}" for member in team]
    return "\n".join(lines)


def format_game_date(value: date) -> str:
    return f"{value:%A}, {value:%B} {value.day}"


def _load_teams(db: Session, game: Game, going: list[Player]) -> Teams | None:
    split = db.get(TeamSplit, game.id)
    if split is None:
        return None
    rows = db.execute(
        select(TeamAssignment, Player)
        .join(Player, Player.id == TeamAssignment.player_id)
        .where(TeamAssignment.game_id == game.id)
    ).all()
    members: dict[str, list[TeamMember]] = {"A": [], "B": []}
    for assignment, player in rows:
        members[assignment.team].append(
            TeamMember(
                name=player.name,
                position=assignment.position,
                on_secondary=assignment.position != player.primary_position,
            )
        )
    for team in members.values():
        team.sort(key=lambda m: (POSITION_ORDER.index(m.position), m.name.lower()))

    assigned_ids = {assignment.player_id for assignment, _ in rows}
    return Teams(
        a=members["A"],
        b=members["B"],
        warnings=split.warnings,
        seed=split.seed,
        is_out_of_date=assigned_ids != {player.id for player in going},
        share_url="https://wa.me/?text="
        + quote(_share_text(game, members["A"], members["B"]), safe=""),
    )


def game_view(db: Session, group: Group, game: Game) -> GameView:
    going = _players_with_status(db, game, "in")
    not_going = _players_with_status(db, game, "out")
    answered = {player.id for player in going + not_going}
    return GameView(
        game=game,
        going=going,
        not_going=not_going,
        no_answer=[player for player in approved_players(db, group) if player.id not in answered],
        teams=_load_teams(db, game, going),
    )
