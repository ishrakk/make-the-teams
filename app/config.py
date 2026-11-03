"""Settings, read from environment variables. The app won't start if one is missing."""

from __future__ import annotations

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str
    session_secret: str = Field(min_length=32)
    group_passcode: str = Field(min_length=4)
    admin_passcode: str = Field(min_length=4)

    game_weekday: int = Field(default=5, ge=0, le=6)  # Monday is 0, Saturday is 5
    timezone: str = "America/New_York"
    secure_cookies: bool = True  # Turn off only for local http://
