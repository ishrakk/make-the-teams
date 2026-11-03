"""Passcode sign-in. Everyone shares one passcode, and organisers share another."""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from app.config import Settings


class SignInRequired(Exception):
    """Raised for signed-out visitors. main.py turns it into a redirect to /login."""


def role_for_passcode(passcode: str, settings: Settings) -> str | None:
    # compare_digest takes the same time however much of the passcode is right.
    entered = passcode.encode()
    is_admin = hmac.compare_digest(entered, settings.admin_passcode.encode())
    is_member = hmac.compare_digest(entered, settings.group_passcode.encode())
    if is_admin:
        return "admin"
    return "member" if is_member else None


def require_member(request: Request) -> None:
    if request.session.get("role") not in ("member", "admin"):
        raise SignInRequired


def require_admin(request: Request) -> None:
    require_member(request)
    if request.session.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Sign in with the organiser passcode.")
