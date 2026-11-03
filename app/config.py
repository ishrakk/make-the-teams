"""Settings, read from environment variables. The app won't start if one is missing."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    session_secret: str = Field(min_length=32)
    # Hides who gave each rating. Changing it stops people editing their past ratings.
    rating_secret: str = Field(min_length=32)
    public_url: str  # The site's address, used in invite and password reset links.

    secure_cookies: bool = True  # Turn off only for local http://
    # Proxies between the internet and the app that add to X-Forwarded-For. Used to
    # find the visitor's address for attempt limits. Leave at 0 with no proxy.
    trusted_proxy_hops: int = Field(default=0, ge=0)

    # Email, for password resets. Without SMTP_HOST, resets are turned off.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = ""
    # Local development only: write emails to the log instead of sending them.
    log_emails: bool = False

    @property
    def password_reset_enabled(self) -> bool:
        return bool(self.smtp_host) or self.log_emails
