"""Try the splitter from a terminal, with no database or web server.

python -m app.splitter app/splitter/examples/roster.csv --seed 7
python -m app.splitter roster.csv --seed 7 --weight off_position=6
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import fields, replace
from pathlib import Path

from app.splitter import DEFAULT_WEIGHTS, Player, Position, SplitResult, Weights, split_teams

COST_TERMS = ("missing_keeper", "extra_keeper", "position_imbalance", "shape", "off_position")


def load_roster(path: Path) -> list[Player]:
    """Read a CSV with the columns: name, primary, secondary (may be blank)."""
    with path.open(newline="") as handle:
        return [
            Player(
                id=row["name"],
                name=row["name"],
                primary=Position(row["primary"].strip().upper()),
                secondary=Position(row["secondary"].strip().upper())
                if row.get("secondary", "").strip()
                else None,
            )
            for row in csv.DictReader(handle)
        ]


def parse_weight(text: str) -> tuple[str, float]:
    name, separator, value = text.partition("=")
    numeric = {f.name for f in fields(Weights)} - {"formation"}
    if not separator or name not in numeric:
        raise argparse.ArgumentTypeError(f"expected NAME=NUMBER, NAME one of {sorted(numeric)}")
    return name, float(value)


def render(result: SplitResult) -> str:
    lines = [f"seed {result.seed}", ""]
    for label, team in (("Team A", result.team_a), ("Team B", result.team_b)):
        lines.append(f"{label} ({len(team)})")
        for assignment in team:
            note = "  (secondary)" if assignment.on_secondary else ""
            lines.append(f"  {assignment.position.value:<4}{assignment.player.name}{note}")
        lines.append("")
    lines.append("Cost")
    for term in COST_TERMS:
        lines.append(f"  {term:<20}{getattr(result.cost, term):>8.2f}")
    lines.append(f"  {'total':<20}{result.cost.total:>8.2f}")
    if result.warnings:
        lines += ["", "Warnings"] + [f"  {warning}" for warning in result.warnings]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Split a roster CSV into two teams.")
    parser.add_argument("roster", type=Path, help="CSV with columns name,primary,secondary")
    parser.add_argument("--seed", type=int, help="repeat a result; omit for a new shuffle")
    parser.add_argument(
        "--weight",
        type=parse_weight,
        action="append",
        default=[],
        metavar="NAME=NUMBER",
        help="override a cost weight; can be repeated",
    )
    args = parser.parse_args()

    weights = replace(DEFAULT_WEIGHTS, **dict(args.weight))
    print(render(split_teams(load_roster(args.roster), seed=args.seed, weights=weights)))


if __name__ == "__main__":
    main()
