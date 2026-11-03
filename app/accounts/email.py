"""Sending email. Password resets are the only email the site sends."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import Settings

logger = logging.getLogger(__name__)


def send_password_reset(settings: Settings, to: str, link: str) -> None:
    message = EmailMessage()
    message["Subject"] = "Reset your Make the Teams password"
    message["From"] = settings.email_from
    message["To"] = to
    message.set_content(
        f"Use this link to choose a new password. It works once, for one hour.\n\n{link}\n\n"
        "If you didn't ask for this, you can ignore this email."
    )
    if settings.log_emails:
        logger.warning("Email for %s:\n%s", to, message.get_content())
        return
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
            server.starttls()
            if settings.smtp_username:
                server.login(settings.smtp_username, settings.smtp_password)
            server.send_message(message)
    except (OSError, smtplib.SMTPException):
        # Runs after the response is sent, so the visitor can't be told. Log the
        # failure without the link, which would let anyone reading logs use it.
        logger.exception("Couldn't send a password reset email")
