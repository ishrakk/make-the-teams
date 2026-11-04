"""Operations on a group's games, attendance and teams.

The website calls these functions, and they connect the database to the splitter.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from urllib.parse import quote
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.db.models import Game, Group, Player, Rsvp, TeamAssignment, TeamSplit
from app.errors import UserError
from app.ratings import service as ratings
from app.splitter import Player as SplitterPlayer
from app.splitter import Position, split_teams

POSITION_LABELS = {
    "GK": "Goalkeeper",
    "DEF": "Defender",
    "MID": "Midfielder",
    "FWD": "Forward",
}
POSITION_ORDER = list(POSITION_LABELS)
LINE_NAMES = {"GK": "goal", "DEF": "defense", "MID": "midfield", "FWD": "attack"}
# Smaller differences between two teams' lines are described as even.
STRONGER_LINE_GAP = 0.3
FACTOR_LABELS = {
    "missing_keeper": "Teams without a keeper",
    "extra_keeper": "Extra keepers on a team",
    "position_imbalance": "Uneven positions between teams",
    "shape": "Distance from a 4-3-3 shape",
    "off_position": "Players on their second position",
    "skill_gap": "Skill difference between teams",
}


def approved_players(db: Session, group: Group) -> list[Player]:
    query = (
        select(Player)
        .where(Player.group_id == group.id, Player.status == "approved")
        .order_by(func.lower(Player.name))
    )
    return list(db.scalars(query))


# Games and attendance


def next_game_date(today: date, weekday: int) -> date:
    """The next game day, which is today if today is a game day."""
    return today + timedelta(days=(weekday - today.weekday()) % 7)


def get_or_create_game(db: Session, group: Group, game_date: date) -> Game:
    # ON CONFLICT handles two people opening the page for a new week at once.
    db.execute(insert(Game).values(group_id=group.id, game_date=game_date).on_conflict_do_nothing())
    db.commit()
    return db.scalars(
        select(Game).where(Game.group_id == group.id, Game.game_date == game_date)
    ).one()


def current_game(db: Session, group: Group) -> Game:
    """This group's next game, by the date where the group plays."""
    today = datetime.now(ZoneInfo(group.timezone)).date()
    return get_or_create_game(db, group, next_game_date(today, group.game_weekday))


def set_attendance(db: Session, game: Game, player: Player, status: str) -> None:
    """Record whether a player is coming. A new answer replaces the old one."""
    if status not in ("in", "out"):
        raise UserError("Choose in or out.")
    statement = insert(Rsvp).values(game_id=game.id, player_id=player.id, status=status)
    db.execute(
        statement.on_conflict_do_update(
            index_elements=[Rsvp.game_id, Rsvp.player_id],
            set_={"status": status, "updated_at": func.now()},
        )
    )
    db.commit()


# Teams


def make_teams(db: Session, game: Game, seed: int | None = None) -> None:
    """Make teams from the players who are in, replacing any earlier teams."""
    # Locking the game means two people pressing the button can't mix results.
    db.execute(select(Game.id).where(Game.id == game.id).with_for_update())
    players = _players_with_status(db, game, "in")
    group = db.get(Group, game.group_id)
    # Free groups are balanced by position only, even if they were paid in the past.
    averages = ratings.averages(db, [player.id for player in players]) if group.has_ratings else {}
    try:
        result = split_teams(
            [
                SplitterPlayer(
                    id=player.id,
                    name=player.name,
                    primary=Position(player.primary_position),
                    secondary=(
                        Position(player.secondary_position) if player.secondary_position else None
                    ),
                    rating=averages[player.id].value if player.id in averages else None,
                )
                for player in players
            ],
            seed=seed,
        )
    except ValueError as error:
        db.rollback()
        raise UserError(str(error)) from error

    db.execute(delete(TeamSplit).where(TeamSplit.game_id == game.id))
    db.add(
        TeamSplit(
            game_id=game.id,
            seed=result.seed,
            cost_total=result.cost.total,
            warnings=list(result.warnings),
            cost_breakdown=asdict(result.cost),
        )
    )
    db.flush()
    for label, team in (("A", result.team_a), ("B", result.team_b)):
        for assignment in team:
            db.add(
                TeamAssignment(
                    game_id=game.id,
                    player_id=assignment.player.id,
                    team=label,
                    position=assignment.position.value,
                    rating=assignment.player.rating,
                )
            )
    db.commit()


# What the game page shows


@dataclass(frozen=True)
class TeamMember:
    name: str
    position: str
    on_secondary: bool
    rating: float | None = None
    primary: str = ""


@dataclass(frozen=True)
class Line:
    """One position on one team."""

    count: int
    rated_count: int
    average: float | None


@dataclass(frozen=True)
class TeamStats:
    score: float | None  # Total rating, with unrated players counted as average
    average: float | None
    lines: dict[str, Line]


@dataclass(frozen=True)
class Explanation:
    """Why the teams came out as they did."""

    a: TeamStats
    b: TeamStats
    reasons: list[str]
    factors: list[tuple[str, float]]
    total: float


@dataclass(frozen=True)
class Teams:
    a: list[TeamMember]
    b: list[TeamMember]
    warnings: list[str]
    seed: int
    is_out_of_date: bool  # The players who are in have changed since teams were made.
    share_url: str
    explanation: Explanation | None


@dataclass(frozen=True)
class GameView:
    game: Game
    going: list[Player]
    not_going: list[Player]
    no_answer: list[Player]
    teams: Teams | None

    def status_of(self, player: Player) -> str | None:
        if player in self.going:
            return "in"
        return "out" if player in self.not_going else None


def _players_with_status(db: Session, game: Game, status: str) -> list[Player]:
    query = (
        select(Player)
        .join(Rsvp, Rsvp.player_id == Player.id)
        .where(Rsvp.game_id == game.id, Rsvp.status == status, Player.status == "approved")
        .order_by(func.lower(Player.name))
    )
    return list(db.scalars(query))


def _share_text(game: Game, a: list[TeamMember], b: list[TeamMember]) -> str:
    lines = [format_game_date(game.game_date)]
    for label, team in (("Team A", a), ("Team B", b)):
        lines += ["", label] + [f"{member.position} {member.name}" for member in team]
    return "\n".join(lines)


def format_game_date(value: date) -> str:
    return f"{value:%A}, {value:%B} {value.day}"


def _team_stats(team: list[TeamMember], fallback: float | None) -> TeamStats:
    lines = {}
    for position in POSITION_ORDER:
        players = [member for member in team if member.position == position]
        rated = [member.rating for member in players if member.rating is not None]
        lines[position] = Line(len(players), len(rated), sum(rated) / len(rated) if rated else None)
    if fallback is None or not team:
        return TeamStats(None, None, lines)
    score = sum(fallback if member.rating is None else member.rating for member in team)
    return TeamStats(score, score / len(team), lines)


def _count_phrase(count: int, singular: str) -> str:
    return f"{count} {singular}" if count == 1 else f"{count} {singular}s"


def _strengths(a: TeamStats, b: TeamStats) -> list[str]:
    """Which team is stronger where, in words so that no rating is revealed."""
    stronger: dict[str, list[str]] = {"A": [], "B": []}
    for position, line_name in LINE_NAMES.items():
        line_a, line_b = a.lines[position], b.lines[position]
        # Comparing one player with one player would rank two individuals.
        if line_a.average is None or line_b.average is None:
            continue
        if line_a.rated_count + line_b.rated_count < 3:
            continue
        difference = line_a.average - line_b.average
        if abs(difference) >= STRONGER_LINE_GAP:
            stronger["A" if difference > 0 else "B"].append(line_name)
    return [
        f"Team {team} is stronger in {' and '.join(lines)}."
        for team, lines in stronger.items()
        if lines
    ]


def _reasons(
    team_a: list[TeamMember],
    team_b: list[TeamMember],
    a: TeamStats,
    b: TeamStats,
    has_ratings: bool,
) -> list[str]:
    reasons = []
    keepers = (a.lines["GK"].count, b.lines["GK"].count)
    if keepers == (1, 1):
        reasons.append("Each team has one keeper.")
    else:
        reasons.append(f"Keepers are split {keepers[0]} and {keepers[1]}.")

    splits = ", ".join(
        f"{a.lines[position].count} and {b.lines[position].count} {label}"
        for position, label in (("DEF", "defenders"), ("MID", "midfielders"), ("FWD", "forwards"))
    )
    reasons.append(f"Positions: {splits}.")

    for member in team_a + team_b:
        if member.on_secondary:
            old = POSITION_LABELS[member.primary].lower()
            new = POSITION_LABELS[member.position].lower()
            reasons.append(
                f"{member.name} moved from {old} to {new}, their second position, "
                "to balance the teams."
            )

    if a.average is None and not has_ratings:
        reasons.append("These teams are balanced by position. Skill balancing is on the paid plan.")
    elif a.average is None:
        reasons.append(
            f"Skill wasn't used, because no player has {ratings.MIN_RATINGS} ratings yet."
        )
    else:
        gap = abs(a.average - b.average)
        reasons.append(
            f"Team A's average rating is {a.average:.2f} and Team B's is {b.average:.2f}, "
            f"a gap of {gap:.2f} on a scale of 1 to 5."
        )
        reasons.extend(_strengths(a, b))
        unrated = sum(member.rating is None for member in team_a + team_b)
        if unrated:
            reasons.append(
                f"{_count_phrase(unrated, 'player')} with fewer than {ratings.MIN_RATINGS} "
                "ratings counted as average."
            )
    return reasons


def _explain(
    team_a: list[TeamMember],
    team_b: list[TeamMember],
    breakdown: dict[str, float] | None,
    has_ratings: bool,
) -> Explanation | None:
    if breakdown is None:
        return None
    rated = [m.rating for m in team_a + team_b if m.rating is not None]
    fallback = sum(rated) / len(rated) if rated else None
    a, b = _team_stats(team_a, fallback), _team_stats(team_b, fallback)
    return Explanation(
        a=a,
        b=b,
        reasons=_reasons(team_a, team_b, a, b, has_ratings),
        factors=[(label, breakdown.get(key, 0.0)) for key, label in FACTOR_LABELS.items()],
        total=sum(breakdown.values()),
    )


def _load_teams(db: Session, group: Group, game: Game, going: list[Player]) -> Teams | None:
    split = db.get(TeamSplit, game.id)
    if split is None:
        return None
    rows = db.execute(
        select(TeamAssignment, Player)
        .join(Player, Player.id == TeamAssignment.player_id)
        .where(TeamAssignment.game_id == game.id)
    ).all()
    members: dict[str, list[TeamMember]] = {"A": [], "B": []}
    for assignment, player in rows:
        members[assignment.team].append(
            TeamMember(
                name=player.name,
                position=assignment.position,
                on_secondary=assignment.position != player.primary_position,
                rating=assignment.rating,
                primary=player.primary_position,
            )
        )
    for team in members.values():
        team.sort(key=lambda m: (POSITION_ORDER.index(m.position), m.name.lower()))

    assigned_ids = {assignment.player_id for assignment, _ in rows}
    return Teams(
        a=members["A"],
        b=members["B"],
        warnings=split.warnings,
        seed=split.seed,
        is_out_of_date=assigned_ids != {player.id for player in going},
        share_url="https://wa.me/?text="
        + quote(_share_text(game, members["A"], members["B"]), safe=""),
        explanation=_explain(members["A"], members["B"], split.cost_breakdown, group.has_ratings),
    )


def game_view(db: Session, group: Group, game: Game) -> GameView:
    going = _players_with_status(db, game, "in")
    not_going = _players_with_status(db, game, "out")
    answered = {player.id for player in going + not_going}
    return GameView(
        game=game,
        going=going,
        not_going=not_going,
        no_answer=[player for player in approved_players(db, group) if player.id not in answered],
        teams=_load_teams(db, group, game, going),
    )
