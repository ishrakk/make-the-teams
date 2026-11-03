"""Signing up, signing in and managing passwords."""

from __future__ import annotations

import hashlib
import re
import secrets
import threading
from datetime import UTC, datetime, timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import PasswordReset, User
from app.errors import UserError

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 128
MAX_EMAIL_LENGTH = 254
RESET_LIFETIME = timedelta(hours=1)
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

_hasher = PasswordHasher()
# Each hash uses 64 MiB by design. Limiting how many run at once stops a burst of
# sign-ins from running a pod out of memory.
_hash_slots = threading.BoundedSemaphore(4)
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _clean_email(email: str) -> str:
    email = normalize_email(email)
    if len(email) > MAX_EMAIL_LENGTH or not EMAIL_PATTERN.fullmatch(email):
        raise UserError("Enter a valid email address.")
    return email


def _hash_password(password: str) -> str:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise UserError(f"Use at least {MIN_PASSWORD_LENGTH} characters for your password.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise UserError(f"Passwords can be up to {MAX_PASSWORD_LENGTH} characters.")
    with _hash_slots:
        return _hasher.hash(password)


def _password_matches(stored_hash: str, password: str) -> bool:
    if len(password) > MAX_PASSWORD_LENGTH:
        return False
    with _hash_slots:
        try:
            return _hasher.verify(stored_hash, password)
        except (VerificationError, InvalidHashError):
            return False


def sign_up(db: Session, email: str, password: str) -> User:
    email = _clean_email(email)
    user = User(email=email, password_hash=_hash_password(password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        raise UserError("That email already has an account. Log in instead.") from error
    return user


def authenticate(db: Session, email: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        # Takes as long as a real check, so timing doesn't reveal who has an account.
        _password_matches(_DUMMY_HASH, password)
        return None
    if not _password_matches(user.password_hash, password):
        return None
    return user


def check_password(user: User, password: str) -> bool:
    return _password_matches(user.password_hash, password)


def change_password(db: Session, user: User, new_password: str) -> None:
    """Set a new password, signing out every device that used the old one."""
    user.password_hash = _hash_password(new_password)
    user.session_epoch += 1
    db.execute(delete(PasswordReset).where(PasswordReset.user_id == user.id))
    db.commit()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_reset_token(db: Session, email: str) -> tuple[str, str] | None:
    """Start a reset. Returns (address, token), or None if there's no such account."""
    now = datetime.now(UTC)
    db.execute(delete(PasswordReset).where(PasswordReset.expires_at < now))
    user = db.scalar(select(User).where(User.email == normalize_email(email)))
    if user is None:
        db.commit()
        return None
    token = secrets.token_urlsafe(32)
    db.add(
        PasswordReset(
            token_hash=_hash_token(token),
            user_id=user.id,
            expires_at=now + RESET_LIFETIME,
        )
    )
    db.commit()
    return user.email, token


def _find_reset(db: Session, token: str) -> PasswordReset | None:
    reset = db.get(PasswordReset, _hash_token(token))
    if reset is None or reset.expires_at < datetime.now(UTC):
        return None
    return reset


def reset_token_is_valid(db: Session, token: str) -> bool:
    return _find_reset(db, token) is not None


def reset_password(db: Session, token: str, new_password: str) -> None:
    reset = _find_reset(db, token)
    if reset is None:
        raise UserError("That reset link has expired. Ask for a new one.")
    change_password(db, db.get(User, reset.user_id), new_password)
