"""See groups and change their plan, until there's billing.

python -m app.groups list
python -m app.groups set-plan <group code> paid
"""

from __future__ import annotations

import argparse
import os
import sys

from sqlalchemy import func, select

from app.db.models import Group, Player
from app.db.session import make_session_factory
from app.errors import UserError
from app.groups import service


def list_groups(db) -> None:
    counts = dict(
        db.execute(
            select(Player.group_id, func.count())
            .where(Player.status == "approved")
            .group_by(Player.group_id)
        ).all()
    )
    print(f"{'PLAN':<6}{'CODE':<16}{'PLAYERS':<9}NAME")
    for group in db.scalars(select(Group).order_by(func.lower(Group.name))):
        code = service.format_code(group.join_code)
        print(f"{group.plan:<6}{code:<16}{counts.get(group.id, 0):<9}{group.name}")


def set_plan(db, code: str, plan: str) -> None:
    group = service.find_by_code(db, code)
    if group is None:
        sys.exit("No group has that code.")
    try:
        service.set_plan(db, group, plan)
    except UserError as error:
        sys.exit(str(error))
    print(f"{group.name} is now on the {plan} plan.")


def main() -> None:
    parser = argparse.ArgumentParser(description="See groups and change their plan.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list", help="list every group")
    change = commands.add_parser("set-plan", help="change a group's plan")
    change.add_argument("code", help="the group's code")
    change.add_argument("plan", choices=service.PLANS)
    args = parser.parse_args()

    with make_session_factory(os.environ["DATABASE_URL"])() as db:
        if args.command == "list":
            list_groups(db)
        else:
            set_plan(db, args.code, args.plan)


if __name__ == "__main__":
    main()
