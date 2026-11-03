"""Create test users: python -m app.demo. Add --reset to start them over."""

from __future__ import annotations

import argparse
import sys

from app.config import Settings
from app.db.session import make_session_factory
from app.demo import seed


def main() -> None:
    parser = argparse.ArgumentParser(description="Create test groups and users.")
    parser.add_argument("--reset", action="store_true", help="delete test data and recreate it")
    args = parser.parse_args()

    settings = Settings()
    if not settings.demo_mode:
        sys.exit("Test users are only for local testing. Set DEMO_MODE=true to create them.")

    with make_session_factory(settings.database_url)() as db:
        if args.reset:
            seed.reset(db)
        if seed.has_demo_data(db):
            print("Test users already exist. Use --reset to start them over.")
            return
        seed.seed(db, settings.rating_secret)
    print("Created test users. Open /demo to switch between them, or log in as")
    print(f"adam@{seed.DEMO_EMAIL_DOMAIN} with the password {seed.DEMO_PASSWORD}.")


if __name__ == "__main__":
    main()
