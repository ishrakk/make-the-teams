"""Operations on players, games, RSVPs and teams.

The web layer calls these functions, and they connect the database to the
splitter. Problems a user can fix raise GameError with a message to show them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from urllib.parse import quote

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Game, Player, Rsvp, TeamAssignment, TeamSplit
from app.splitter import Player as SplitterPlayer
from app.splitter import Position, split_teams

MAX_NAME_LENGTH = 60
POSITION_LABELS = {
    "GK": "Goalkeeper",
    "DEF": "Defender",
    "MID": "Midfielder",
    "FWD": "Forward",
}
POSITION_ORDER = list(POSITION_LABELS)


class GameError(Exception):
    """A problem the user can fix. The message is shown to them."""


# Players


def active_players(db: Session) -> list[Player]:
    query = select(Player).where(Player.active).order_by(func.lower(Player.name))
    return list(db.scalars(query))


def _clean_player_fields(name: str, primary: str, secondary: str) -> tuple[str, str, str | None]:
    name = " ".join(name.split())
    if not name:
        raise GameError("Enter a name.")
    if len(name) > MAX_NAME_LENGTH:
        raise GameError(f"Names can be up to {MAX_NAME_LENGTH} characters.")
    if primary not in POSITION_LABELS:
        raise GameError("Choose a main position.")
    if secondary and secondary not in POSITION_LABELS:
        raise GameError("Choose a valid second position.")
    if secondary == primary:
        raise GameError("Your second position must differ from your main position.")
    return name, primary, secondary or None


def _find_by_name(db: Session, name: str) -> Player | None:
    return db.scalar(select(Player).where(func.lower(Player.name) == name.lower()))


def add_player(db: Session, name: str, primary: str, secondary: str = "") -> Player:
    """Add a player. A removed player with the same name is brought back."""
    name, primary, secondary = _clean_player_fields(name, primary, secondary)
    player = _find_by_name(db, name)
    if player and player.active:
        raise GameError(f"{player.name} is already on the list.")
    if player is None:
        player = Player(name=name)
        db.add(player)
    player.name = name
    player.primary_position = primary
    player.secondary_position = secondary
    player.active = True
    db.commit()
    return player


def update_player(
    db: Session, player_id: int, name: str, primary: str, secondary: str = ""
) -> None:
    name, primary, secondary = _clean_player_fields(name, primary, secondary)
    player = get_active_player(db, player_id)
    other = _find_by_name(db, name)
    if other and other.id != player.id:
        raise GameError(f"The name {other.name} is already taken.")
    player.name = name
    player.primary_position = primary
    player.secondary_position = secondary
    db.commit()


def remove_player(db: Session, player_id: int) -> None:
    """Hide a player from future games. Past teams still show them."""
    get_active_player(db, player_id).active = False
    db.commit()


def get_active_player(db: Session, player_id: int) -> Player:
    player = db.get(Player, player_id)
    if player is None or not player.active:
        raise GameError("That player isn't on the list.")
    return player


# Games and RSVPs


def next_game_date(today: date, weekday: int) -> date:
    """The next game day, which is today if today is a game day."""
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def get_or_create_game(db: Session, game_date: date) -> Game:
    # ON CONFLICT handles two people opening the page for a new week at once.
    db.execute(insert(Game).values(game_date=game_date).on_conflict_do_nothing())
    db.commit()
    return db.scalars(select(Game).where(Game.game_date == game_date)).one()


def set_rsvp(db: Session, game: Game, player_id: int, status: str) -> Player:
    if status not in ("in", "out"):
        raise GameError("Choose in or out.")
    player = get_active_player(db, player_id)
    statement = insert(Rsvp).values(game_id=game.id, player_id=player.id, status=status)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[Rsvp.game_id, Rsvp.player_id],
            set_={"status": status, "updated_at": func.now()},
        )
    )
    db.commit()
    return player


# Teams


def make_teams(db: Session, game: Game, seed: int | None = None) -> None:
    """Make teams from the players who are in, replacing any earlier teams."""
    # Locking the game means two people pressing the button can't mix results.
    db.execute(select(Game.id).where(Game.id == game.id).with_for_update())
    players = _players_with_status(db, game, "in")
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
                )
                for player in players
            ],
            seed=seed,
        )
    except ValueError as error:
        db.rollback()
        raise GameError(str(error)) from error

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


def _players_with_status(db: Session, game: Game, status: str) -> list[Player]:
    query = (
        select(Player)
        .join(Rsvp, Rsvp.player_id == Player.id)
        .where(Rsvp.game_id == game.id, Rsvp.status == status, Player.active)
        .order_by(func.lower(Player.name))
    )
    return list(db.scalars(query))


def _share_text(game: Game, a: list[TeamMember], b: list[TeamMember]) -> str:
    lines = [format_game_date(game.game_date)]
    for label, team in (("Team A", a), ("Team B", b)):
        lines += ["", label] + [f"{member.position} {member.name}" for member in team]
    return "\n".join(lines)


def format_game_date(value: date) -> str:
    return f"{value:%A} {value.day} {value:%B}"


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


def game_view(db: Session, game: Game) -> GameView:
    going = _players_with_status(db, game, "in")
    not_going = _players_with_status(db, game, "out")
    answered = {player.id for player in going + not_going}
    return GameView(
        game=game,
        going=going,
        not_going=not_going,
        no_answer=[player for player in active_players(db) if player.id not in answered],
        teams=_load_teams(db, game, going),
    )
