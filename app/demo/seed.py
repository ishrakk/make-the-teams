"""Creates test groups and players, using the same functions as the real site."""

from __future__ import annotations

import random
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.accounts import service as accounts
from app.db.models import Group, Player, User
from app.games import service as games
from app.groups import service as groups
from app.ratings import service as ratings

DEMO_EMAIL_DOMAIN = "example.test"  # Reserved for testing, so it can't be a real address.
DEMO_PASSWORD = "demo-password"
SATURDAY_CODE = "DEMASATVRDAY"
THURSDAY_CODE = "DEMATHVRSDAY"
SATURDAY = "5"
THURSDAY = "3"
TIMEZONE = "America/New_York"

# name, main position, second position, the ability others tend to rate them at
PLAYERS = [
    ("Adam", "GK", "", 3),
    ("Bilal", "GK", "DEF", 4),
    ("Carlos", "DEF", "MID", 5),
    ("Dev", "DEF", "", 3),
    ("Eli", "DEF", "FWD", 2),
    ("Farid", "DEF", "MID", 4),
    ("Gabe", "DEF", "", 3),
    ("Hassan", "MID", "FWD", 5),
    ("Ivan", "MID", "DEF", 3),
    ("Jamal", "MID", "", 4),
    ("Kofi", "FWD", "MID", 5),
    ("Liam", "FWD", "", 2),
    ("Marco", "FWD", "MID", 4),
    ("Nabil", "FWD", "", 1),
]
SATURDAY_OUT = {"Gabe", "Marco"}
SATURDAY_NO_ANSWER = {"Liam"}
SATURDAY_PENDING = "Omar"
THURSDAY_PLAYERS = {"Adam", "Bilal", "Dev", "Hassan", "Kofi", "Nabil"}


def is_demo_email(email: str) -> bool:
    return email.endswith(f"@{DEMO_EMAIL_DOMAIN}")


def _email(name: str) -> str:
    return f"{name.lower()}@{DEMO_EMAIL_DOMAIN}"


def has_demo_data(db: Session) -> bool:
    return db.scalar(select(Group.id).where(Group.join_code == SATURDAY_CODE)) is not None


def reset(db: Session) -> None:
    """Delete the test groups and users. Other data isn't touched."""
    db.execute(delete(Group).where(Group.join_code.in_([SATURDAY_CODE, THURSDAY_CODE])))
    db.execute(delete(User).where(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}")))
    db.commit()


def _approve(
    db: Session, group: Group, user: User, name: str, primary: str, secondary: str
) -> Player:
    player = groups.request_to_join(db, group, user, name, primary, secondary)
    groups.approve_request(db, group, player.id)
    return player


def seed(db: Session, rating_secret: str) -> None:
    users = {
        name: accounts.sign_up(db, _email(name), DEMO_PASSWORD)
        for name in [row[0] for row in PLAYERS] + [SATURDAY_PENDING]
    }

    saturday = groups.create_group(
        db, users["Adam"], "Saturday Crew", SATURDAY, TIMEZONE, "Adam", "GK"
    )
    saturday.join_code = SATURDAY_CODE
    players = {"Adam": groups.player_for(db, saturday, users["Adam"])}
    for name, primary, secondary, _ in PLAYERS[1:]:
        players[name] = _approve(db, saturday, users[name], name, primary, secondary)
    groups.request_to_join(db, saturday, users[SATURDAY_PENDING], SATURDAY_PENDING, "MID")

    game = games.current_game(db, saturday)
    for name, player in players.items():
        if name in SATURDAY_NO_ANSWER:
            continue
        games.set_attendance(db, game, player, "out" if name in SATURDAY_OUT else "in")

    # Everyone rates everyone, close to the player's ability. Fixed so runs match.
    rng = random.Random(7)
    ability = {name: level for name, _, _, level in PLAYERS}
    for rater_name, rater in players.items():
        scores = {
            player.id: max(1, min(5, ability[name] + rng.choice([-1, 0, 0, 0, 1])))
            for name, player in players.items()
            if name != rater_name
        }
        ratings.save_ratings(db, rating_secret, rater, scores)

    thursday = groups.create_group(
        db, users["Bilal"], "Thursday Night", THURSDAY, TIMEZONE, "Bilal", "GK", "DEF"
    )
    thursday.join_code = THURSDAY_CODE
    for name, primary, secondary, _ in PLAYERS:
        if name in THURSDAY_PLAYERS and name != "Bilal":
            _approve(db, thursday, users[name], name, primary, secondary)
    db.commit()


@dataclass(frozen=True)
class DemoAccount:
    user: User
    name: str
    summary: str


def demo_accounts(db: Session) -> list[DemoAccount]:
    users = db.scalars(
        select(User).where(User.email.like(f"%@{DEMO_EMAIL_DOMAIN}")).order_by(User.email)
    ).all()
    accounts_list = []
    for user in users:
        rows = groups.user_groups(db, user)
        parts = []
        for group, player in rows:
            role = {"admin": "admin"}.get(player.role, "member")
            if player.status == "pending":
                role = "waiting for approval"
            parts.append(f"{group.name}: {role}")
        name = rows[0][1].name if rows else user.email.split("@")[0].title()
        accounts_list.append(DemoAccount(user, name, ", ".join(parts) or "Not in a group"))
    return accounts_list
