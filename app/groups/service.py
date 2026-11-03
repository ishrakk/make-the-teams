"""Creating groups, joining them, and what admins can do."""

from __future__ import annotations

import secrets
from zoneinfo import available_timezones

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Group, Player, User
from app.errors import UserError
from app.games.service import POSITION_LABELS
from app.ratings import service as ratings

# Leaves out 0, 1, I, L, O and U, which are easy to misread or mistype.
CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LENGTH = 12  # About 59 bits of randomness
MAX_NAME_LENGTH = 60
MAX_PLAYERS_PER_GROUP = 100

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DEFAULT_WEEKDAY = 5
DEFAULT_TIMEZONE = "America/New_York"
TIMEZONES = tuple(
    sorted(
        zone
        for zone in available_timezones()
        if "/" in zone and not zone.startswith(("Etc/", "posix/", "right/", "SystemV/", "US/"))
    )
)


def new_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(text: str) -> str:
    """Accept codes with any spacing, dashes or capitalization."""
    return "".join(character for character in text.upper() if character.isalnum())


def format_code(code: str) -> str:
    """Make a code easier to read: ABCD-EFGH-JKMN."""
    return "-".join(code[start : start + 4] for start in range(0, len(code), 4))


def find_by_code(db: Session, text: str) -> Group | None:
    return db.scalar(select(Group).where(Group.join_code == normalize_code(text)))


# Field checks


def _clean_group_fields(name: str, weekday: str, timezone: str) -> tuple[str, int, str]:
    name = " ".join(name.split())
    if not name:
        raise UserError("Enter a group name.")
    if len(name) > MAX_NAME_LENGTH:
        raise UserError(f"Group names can be up to {MAX_NAME_LENGTH} characters.")
    if weekday not in {str(index) for index in range(7)}:
        raise UserError("Choose a game day.")
    if timezone not in available_timezones():
        raise UserError("Choose a time zone.")
    return name, int(weekday), timezone


def _clean_player_fields(name: str, primary: str, secondary: str) -> tuple[str, str, str | None]:
    name = " ".join(name.split())
    if not name:
        raise UserError("Enter your name.")
    if len(name) > MAX_NAME_LENGTH:
        raise UserError(f"Names can be up to {MAX_NAME_LENGTH} characters.")
    if primary not in POSITION_LABELS:
        raise UserError("Choose a main position.")
    if secondary and secondary not in POSITION_LABELS:
        raise UserError("Choose a valid second position.")
    if secondary == primary:
        raise UserError("Your second position must differ from your main position.")
    return name, primary, secondary or None


def _commit_player_change(db: Session, name: str) -> None:
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise UserError(f"Someone in this group already uses the name {name}.") from error


# Creating and joining


def create_group(
    db: Session,
    user: User,
    name: str,
    weekday: str,
    timezone: str,
    player_name: str,
    primary: str,
    secondary: str = "",
) -> Group:
    """Create a group, with its creator as its first admin."""
    name, weekday_number, timezone = _clean_group_fields(name, weekday, timezone)
    player_name, primary, secondary = _clean_player_fields(player_name, primary, secondary)
    group = Group(
        name=name,
        join_code=new_code(),
        game_weekday=weekday_number,
        timezone=timezone,
    )
    db.add(group)
    db.flush()
    db.add(
        Player(
            group_id=group.id,
            user_id=user.id,
            name=player_name,
            primary_position=primary,
            secondary_position=secondary,
            role="admin",
            status="approved",
        )
    )
    db.commit()
    return group


def player_for(db: Session, group: Group, user: User) -> Player | None:
    return db.scalar(select(Player).where(Player.group_id == group.id, Player.user_id == user.id))


def request_to_join(
    db: Session, group: Group, user: User, name: str, primary: str, secondary: str = ""
) -> Player:
    """Ask to join a group. Someone previously removed can ask again."""
    name, primary, secondary = _clean_player_fields(name, primary, secondary)
    player = player_for(db, group, user)
    if player and player.status != "removed":
        raise UserError("You've already asked to join this group.")
    active_count = db.scalar(
        select(func.count())
        .select_from(Player)
        .where(Player.group_id == group.id, Player.status != "removed")
    )
    if active_count >= MAX_PLAYERS_PER_GROUP:
        raise UserError(f"This group has reached its limit of {MAX_PLAYERS_PER_GROUP} players.")
    if player is None:
        player = Player(group_id=group.id, user_id=user.id)
        db.add(player)
    player.name = name
    player.primary_position = primary
    player.secondary_position = secondary
    player.role = "member"
    player.status = "pending"
    _commit_player_change(db, name)
    return player


def user_groups(db: Session, user: User) -> list[tuple[Group, Player]]:
    rows = db.execute(
        select(Group, Player)
        .join(Player, Player.group_id == Group.id)
        .where(Player.user_id == user.id, Player.status != "removed")
        .order_by(func.lower(Group.name))
    )
    return [(group, player) for group, player in rows]


def update_profile(db: Session, player: Player, name: str, primary: str, secondary: str) -> None:
    player.name, player.primary_position, player.secondary_position = _clean_player_fields(
        name, primary, secondary
    )
    _commit_player_change(db, player.name)


# What admins can do


def _player_in_group(db: Session, group: Group, player_id: int) -> Player:
    """Find a player in this group. Other groups' players count as not found."""
    player = db.get(Player, player_id)
    if player is None or player.group_id != group.id or player.status == "removed":
        raise UserError("That player isn't in this group.")
    return player


def pending_requests(db: Session, group: Group) -> list[Player]:
    query = (
        select(Player)
        .where(Player.group_id == group.id, Player.status == "pending")
        .order_by(Player.created_at)
    )
    return list(db.scalars(query))


def approve_request(db: Session, group: Group, player_id: int) -> Player:
    player = _player_in_group(db, group, player_id)
    if player.status != "pending":
        raise UserError(f"{player.name} is already in the group.")
    player.status = "approved"
    db.commit()
    return player


def decline_request(db: Session, group: Group, player_id: int) -> Player:
    player = _player_in_group(db, group, player_id)
    if player.status != "pending":
        raise UserError(f"{player.name} is already in the group.")
    player.status = "removed"
    db.commit()
    return player


def _is_last_admin(db: Session, player: Player) -> bool:
    if player.role != "admin":
        return False
    admins = db.scalar(
        select(func.count())
        .select_from(Player)
        .where(
            Player.group_id == player.group_id,
            Player.role == "admin",
            Player.status == "approved",
        )
    )
    return admins == 1


def set_role(db: Session, group: Group, player_id: int, role: str) -> Player:
    player = _player_in_group(db, group, player_id)
    if role not in ("member", "admin") or player.status != "approved":
        raise UserError("Only approved players can be admins.")
    if role == "member" and _is_last_admin(db, player):
        raise UserError("A group needs at least one admin. Make someone else an admin first.")
    player.role = role
    db.commit()
    return player


def _remove(db: Session, secret: str, player: Player) -> None:
    if _is_last_admin(db, player):
        raise UserError(
            "A group needs at least one admin. Make someone else an admin, or delete the group."
        )
    ratings.forget_player(db, secret, player)
    player.status = "removed"
    player.role = "member"
    db.commit()


def remove_player(db: Session, secret: str, group: Group, player_id: int) -> Player:
    player = _player_in_group(db, group, player_id)
    _remove(db, secret, player)
    return player


def leave_group(db: Session, secret: str, player: Player) -> None:
    _remove(db, secret, player)


def update_group(db: Session, group: Group, name: str, weekday: str, timezone: str) -> None:
    group.name, group.game_weekday, group.timezone = _clean_group_fields(name, weekday, timezone)
    db.commit()


def replace_code(db: Session, group: Group) -> None:
    """Replace the group code. People already in the group aren't affected."""
    group.join_code = new_code()
    db.commit()


def delete_group(db: Session, group: Group, confirmation: str) -> None:
    """Delete a group and everything in it. This can't be undone."""
    if " ".join(confirmation.split()).lower() != group.name.lower():
        raise UserError("Type the group's name exactly to delete it.")
    db.execute(delete(Group).where(Group.id == group.id))
    db.commit()


def delete_account(db: Session, secret: str, user: User) -> None:
    """Delete an account and its player in every group."""
    players = db.scalars(
        select(Player).where(Player.user_id == user.id, Player.status != "removed")
    ).all()
    for player in players:
        if _is_last_admin(db, player):
            group = db.get(Group, player.group_id)
            raise UserError(
                f"You're the only admin of {group.name}. Make someone else an admin, "
                "or delete the group, first."
            )
    all_players = db.scalars(select(Player).where(Player.user_id == user.id)).all()
    for player in all_players:
        ratings.forget_player(db, secret, player)
    db.execute(delete(User).where(User.id == user.id))
    db.commit()
