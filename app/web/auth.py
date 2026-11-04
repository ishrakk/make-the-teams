"""Who the visitor is: their account, and their player in the group they're viewing."""

from __future__ import annotations

import hashlib
import hmac
from collections.abc import Iterator
from dataclasses import dataclass

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.db.models import Group, Player, User
from app.groups import service as groups


class SignInRequired(Exception):
    """Raised for signed-out visitors. main.py sends them to the login page."""


class NoGroup(Exception):
    """Raised when a signed-in visitor isn't in a group yet. main.py sends them to /groups."""


@dataclass(frozen=True)
class Membership:
    user: User
    group: Group
    player: Player


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def sign_in(request: Request, user: User) -> str:
    """Start a session. Returns the page the visitor was on their way to."""
    next_path = request.session.get("next", "/groups")
    request.session.clear()
    request.session.update(user_id=user.id, epoch=user.session_epoch)
    return next_path


def session_user(request: Request, db: Session) -> User | None:
    """The signed-in user. A changed password ends sessions from before the change."""
    user_id = request.session.get("user_id")
    if user_id is None:
        return None
    user = db.get(User, user_id)
    if user is None or request.session.get("epoch") != user.session_epoch:
        request.session.clear()
        return None
    return user


def require_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = session_user(request, db)
    if user is None:
        raise SignInRequired
    return user


def membership_for(request: Request, db: Session, user: User) -> Membership | None:
    """The group being viewed: the last one chosen, or the first this user is approved in."""
    approved = [
        (group, player)
        for group, player in groups.user_groups(db, user)
        if player.status == "approved"
    ]
    if not approved:
        return None
    wanted = request.session.get("group_id")
    group, player = next((row for row in approved if row[0].id == wanted), approved[0])
    request.session["group_id"] = group.id
    return Membership(user, group, player)


def require_member(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> Membership:
    membership = membership_for(request, db, user)
    if membership is None:
        raise NoGroup
    return membership


def require_admin(membership: Membership = Depends(require_member)) -> Membership:
    if membership.player.role != "admin":
        raise HTTPException(status_code=403, detail="Only a group admin can do this.")
    return membership


def visitor_key(request: Request) -> str:
    """Identify a visitor for attempt limits, without storing their address."""
    settings = request.app.state.settings
    address = request.client.host if request.client else "unknown"
    if settings.trusted_proxy_hops:
        # Only the entries added by our own proxies can be trusted. Anything further
        # left came from the visitor, who could have written whatever they liked.
        forwarded = request.headers.get("x-forwarded-for", "").split(",")
        if len(forwarded) >= settings.trusted_proxy_hops:
            address = forwarded[-settings.trusted_proxy_hops].strip()
    secret = settings.session_secret.encode()
    return hmac.new(secret, address.encode(), hashlib.sha256).hexdigest()[:32]


def email_key(request: Request, email: str) -> str:
    """Identify an email address for attempt limits, without storing it in the counts."""
    secret = request.app.state.settings.session_secret.encode()
    return hmac.new(secret, email.encode(), hashlib.sha256).hexdigest()[:32]
