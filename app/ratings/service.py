"""Anonymous 1 to 5 ratings of other players in a group.

The table never stores who gave a score. Each row has a tag calculated with a
keyed hash from the rater and the player being rated. With the key, the app can find
a person's own score to update it. Without the key, someone reading the database
can't tell who gave a score, or whether two scores came from the same person.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Player, Rating
from app.errors import UserError

MIN_SCORE = 1
MAX_SCORE = 5
# Below this, an average isn't shown or used. It could reveal a single person's
# score, and one person's opinion shouldn't move the teams.
MIN_RATINGS = 3


@dataclass(frozen=True)
class Average:
    value: float
    count: int


def rater_tag(secret: str, rater_id: int, rated_id: int) -> str:
    message = f"{rater_id}:{rated_id}".encode()
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def _group_player_ids(db: Session, group_id: int) -> list[int]:
    return list(db.scalars(select(Player.id).where(Player.group_id == group_id)))


def save_ratings(db: Session, secret: str, rater: Player, scores: dict[int, int]) -> int:
    """Save the rater's scores, replacing earlier ones. Returns how many were saved."""
    approved_others = set(
        db.scalars(
            select(Player.id).where(
                Player.group_id == rater.group_id,
                Player.status == "approved",
                Player.id != rater.id,
            )
        )
    )
    for rated_id, score in scores.items():
        if rated_id not in approved_others:
            raise UserError("You can only rate other players in your group.")
        if not MIN_SCORE <= score <= MAX_SCORE:
            raise UserError(f"Ratings go from {MIN_SCORE} to {MAX_SCORE}.")
    for rated_id, score in scores.items():
        statement = insert(Rating).values(
            rated_player_id=rated_id,
            rater_tag=rater_tag(secret, rater.id, rated_id),
            score=score,
        )
        db.execute(
            statement.on_conflict_do_update(
                index_elements=[Rating.rated_player_id, Rating.rater_tag],
                set_={"score": score},
            )
        )
    db.commit()
    return len(scores)


def my_ratings(db: Session, secret: str, rater: Player, player_ids: list[int]) -> dict[int, int]:
    """The rater's own earlier scores, so they can see and change them."""
    tags = {rater_tag(secret, rater.id, rated_id): rated_id for rated_id in player_ids}
    if not tags:
        return {}
    rows = db.execute(select(Rating.rater_tag, Rating.score).where(Rating.rater_tag.in_(tags)))
    return {tags[tag]: score for tag, score in rows}


def averages(db: Session, player_ids: list[int]) -> dict[int, Average]:
    """Averages for players with enough ratings. Others are left out."""
    if not player_ids:
        return {}
    rows = db.execute(
        select(Rating.rated_player_id, func.avg(Rating.score), func.count())
        .where(Rating.rated_player_id.in_(player_ids))
        .group_by(Rating.rated_player_id)
        .having(func.count() >= MIN_RATINGS)
    )
    return {player_id: Average(float(value), count) for player_id, value, count in rows}


def forget_player(db: Session, secret: str, player: Player) -> None:
    """Delete the scores a player gave and received, when they leave a group."""
    tags = [
        rater_tag(secret, player.id, other_id)
        for other_id in _group_player_ids(db, player.group_id)
    ]
    db.execute(delete(Rating).where(Rating.rater_tag.in_(tags)))
    db.execute(delete(Rating).where(Rating.rated_player_id == player.id))
