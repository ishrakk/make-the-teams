"""Pages, form handlers and health checks. Rules live in the other app modules."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import ratelimit
from app.accounts import email as account_email
from app.accounts import service as accounts
from app.db.models import User
from app.errors import UserError
from app.games import service as games
from app.games.service import TeamMember
from app.groups import service as groups
from app.ratings import service as ratings
from app.web.auth import (
    Membership,
    email_key,
    get_db,
    membership_for,
    require_admin,
    require_member,
    require_user,
    session_user,
    sign_in,
    visitor_key,
)

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")

# The illustration on the home page.
EXAMPLE_TEAM_A = [
    TeamMember("Sam", "GK", False),
    TeamMember("Alex", "DEF", False),
    TeamMember("Priya", "DEF", False),
    TeamMember("Marco", "MID", False),
    TeamMember("Noor", "FWD", False),
]
EXAMPLE_TEAM_B = [
    TeamMember("Jo", "GK", False),
    TeamMember("Dan", "DEF", False),
    TeamMember("Kofi", "DEF", False),
    TeamMember("Lena", "MID", False),
    TeamMember("Omar", "FWD", False),
]
GROUP_FIELD_OPTIONS = {"weekdays": groups.WEEKDAYS, "timezones": groups.TIMEZONES}
GROUP_DESTINATIONS = {"game": "/", "details": "/group", "configure": "/group/configure"}
TOO_MANY_CODES = "Too many wrong codes. Try again in 15 minutes."


def render(request: Request, template: str, **context) -> HTMLResponse:
    context["message"] = request.session.pop("message", None)
    context["error"] = request.session.pop("error", None)
    context["signed_in"] = "user_id" in request.session
    context["position_labels"] = games.POSITION_LABELS
    context["demo_mode"] = settings_of(request).demo_mode
    context["demo_email"] = request.session.get("demo_email")
    return templates.TemplateResponse(request, template, context)


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


def settings_of(request: Request):
    return request.app.state.settings


def base_url(request: Request) -> str:
    return settings_of(request).public_url.rstrip("/")


def rating_secret(request: Request) -> str:
    return settings_of(request).rating_secret


async def form_data(request: Request):
    return await request.form()


# Health checks, used by Kubernetes


@router.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
def readyz(db: Session = Depends(get_db)) -> JSONResponse:
    try:
        db.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return JSONResponse({"status": "database unavailable"}, status_code=503)
    return JSONResponse({"status": "ok"})


# The home page: the game for people in a group, an introduction for everyone else


@router.get("/")
def home(request: Request, db: Session = Depends(get_db)) -> Response:
    user = session_user(request, db)
    if user is None:
        return render(request, "landing.html", team_a=EXAMPLE_TEAM_A, team_b=EXAMPLE_TEAM_B)
    membership = membership_for(request, db, user)
    if membership is None:
        return redirect("/groups")
    view = games.game_view(db, membership.group, games.current_game(db, membership.group))
    return render(
        request,
        "game.html",
        group=membership.group,
        player=membership.player,
        is_admin=membership.player.role == "admin",
        view=view,
        my_status=view.status_of(membership.player),
        game_date=games.format_game_date(view.game.game_date),
    )


# Accounts


@router.get("/signup")
def signup_page(request: Request, db: Session = Depends(get_db)) -> Response:
    if session_user(request, db):
        return redirect("/")
    return render(request, "signup.html", min_length=accounts.MIN_PASSWORD_LENGTH)


@router.post("/signup")
def signup(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    visitor = visitor_key(request)
    if ratelimit.is_blocked(db, ratelimit.SIGNUP_PER_VISITOR, visitor):
        request.session["error"] = "Too many new accounts today. Try again tomorrow."
        return redirect("/signup")
    try:
        user = accounts.sign_up(db, email, password)
    except UserError as error:
        request.session["error"] = str(error)
        return redirect("/signup")
    ratelimit.record(db, ratelimit.SIGNUP_PER_VISITOR, visitor)
    return redirect(sign_in(request, user))


@router.get("/login")
def login_page(request: Request, db: Session = Depends(get_db)) -> Response:
    if session_user(request, db):
        return redirect("/")
    return render(request, "login.html", reset_enabled=settings_of(request).password_reset_enabled)


@router.post("/login")
def login(
    request: Request,
    email: str = Form(""),
    password: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    visitor = visitor_key(request)
    address = email_key(request, accounts.normalize_email(email))
    if ratelimit.is_blocked(
        db, ratelimit.WRONG_PASSWORD_PER_VISITOR, visitor
    ) or ratelimit.is_blocked(db, ratelimit.WRONG_PASSWORD_PER_EMAIL, address):
        request.session["error"] = "Too many wrong passwords. Try again in 15 minutes."
        return redirect("/login")
    user = accounts.authenticate(db, email, password)
    if user is None:
        ratelimit.record(db, ratelimit.WRONG_PASSWORD_PER_VISITOR, visitor)
        ratelimit.record(db, ratelimit.WRONG_PASSWORD_PER_EMAIL, address)
        request.session["error"] = "That email and password don't match."
        return redirect("/login")
    return redirect(sign_in(request, user))


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return redirect("/")


@router.get("/forgot")
def forgot_page(request: Request) -> HTMLResponse:
    return render(request, "forgot.html", reset_enabled=settings_of(request).password_reset_enabled)


@router.post("/forgot")
def forgot(
    request: Request,
    background: BackgroundTasks,
    email: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    settings = settings_of(request)
    if not settings.password_reset_enabled:
        return redirect("/forgot")
    visitor = visitor_key(request)
    address = email_key(request, accounts.normalize_email(email))
    # The same message every time, so this can't reveal who has an account.
    request.session["message"] = "If that email has an account, a reset link is on its way."
    if ratelimit.is_blocked(db, ratelimit.RESET_PER_VISITOR, visitor) or ratelimit.is_blocked(
        db, ratelimit.RESET_PER_EMAIL, address
    ):
        return redirect("/login")
    ratelimit.record(db, ratelimit.RESET_PER_VISITOR, visitor)
    ratelimit.record(db, ratelimit.RESET_PER_EMAIL, address)
    created = accounts.create_reset_token(db, email)
    if created:
        to, token = created
        link = f"{base_url(request)}/reset/{token}"
        background.add_task(account_email.send_password_reset, settings, to, link)
    return redirect("/login")


@router.get("/reset/{token}")
def reset_page(request: Request, token: str, db: Session = Depends(get_db)) -> Response:
    if not accounts.reset_token_is_valid(db, token):
        request.session["error"] = "That reset link has expired. Ask for a new one."
        return redirect("/forgot")
    return render(request, "reset.html", token=token, min_length=accounts.MIN_PASSWORD_LENGTH)


@router.post("/reset/{token}")
def reset(
    request: Request,
    token: str,
    password: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        accounts.reset_password(db, token, password)
    except UserError as error:
        request.session["error"] = str(error)
        return redirect(f"/reset/{token}")
    request.session.clear()
    request.session["message"] = "Password changed. Log in with your new password."
    return redirect("/login")


@router.get("/account")
def account_page(request: Request, user: User = Depends(require_user)) -> HTMLResponse:
    return render(request, "account.html", user=user, min_length=accounts.MIN_PASSWORD_LENGTH)


@router.post("/account/password")
def change_password(
    request: Request,
    current_password: str = Form(""),
    new_password: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not accounts.check_password(user, current_password):
        request.session["error"] = "Your current password isn't right."
        return redirect("/account")
    try:
        accounts.change_password(db, user, new_password)
    except UserError as error:
        request.session["error"] = str(error)
        return redirect("/account")
    group_id = request.session.get("group_id")
    sign_in(request, user)
    if group_id:
        request.session["group_id"] = group_id
    request.session["message"] = "Password changed. Your other devices have been signed out."
    return redirect("/account")


@router.post("/account/delete")
def delete_account(
    request: Request,
    password: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    if not accounts.check_password(user, password):
        request.session["error"] = "That password isn't right, so your account wasn't deleted."
        return redirect("/account")
    try:
        groups.delete_account(db, rating_secret(request), user)
    except UserError as error:
        db.rollback()
        request.session["error"] = str(error)
        return redirect("/account")
    request.session.clear()
    request.session["message"] = "Your account has been deleted."
    return redirect("/")


# Your groups, creating one and joining one


@router.get("/groups")
def groups_page(
    request: Request,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    cards = []
    for group, player in groups.user_groups(db, user):
        view = None
        if player.status == "approved":
            view = games.game_view(db, group, games.current_game(db, group))
        cards.append(
            {
                "group": group,
                "player": player,
                "view": view,
                "game_date": games.format_game_date(view.game.game_date) if view else None,
                "my_status": view.status_of(player) if view else None,
                "waiting": len(groups.pending_requests(db, group))
                if view and player.role == "admin"
                else 0,
            }
        )
    return render(request, "groups.html", cards=cards)


@router.post("/groups/{group_id}/open")
def open_group(
    request: Request,
    group_id: int,
    to: str = Form("game"),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    request.session["group_id"] = group_id
    membership = membership_for(request, db, user)
    # membership_for falls back to another group if this user isn't approved in this one.
    if membership is None or membership.group.id != group_id:
        request.session["error"] = "You're not in that group."
        return redirect("/groups")
    return redirect(GROUP_DESTINATIONS.get(to, "/"))


@router.get("/groups/new")
def new_group_page(request: Request, user: User = Depends(require_user)) -> HTMLResponse:
    return render(
        request,
        "group_new.html",
        **GROUP_FIELD_OPTIONS,
        current_name="",
        current_weekday=groups.DEFAULT_WEEKDAY,
        current_timezone=groups.DEFAULT_TIMEZONE,
    )


@router.post("/groups")
def create_group(
    request: Request,
    name: str = Form(""),
    weekday: str = Form(""),
    timezone: str = Form(""),
    player_name: str = Form(""),
    primary: str = Form(""),
    secondary: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    visitor = visitor_key(request)
    if ratelimit.is_blocked(db, ratelimit.GROUPS_PER_VISITOR, visitor) or ratelimit.is_blocked(
        db, ratelimit.GROUPS_SITEWIDE
    ):
        request.session["error"] = "Too many new groups today. Try again tomorrow."
        return redirect("/groups/new")
    try:
        group = groups.create_group(
            db, user, name, weekday, timezone, player_name, primary, secondary
        )
    except UserError as error:
        db.rollback()
        request.session["error"] = str(error)
        return redirect("/groups/new")
    ratelimit.record(db, ratelimit.GROUPS_PER_VISITOR, visitor)
    ratelimit.record(db, ratelimit.GROUPS_SITEWIDE)
    request.session["group_id"] = group.id
    request.session["message"] = f"{group.name} is ready. Invite your friends."
    return redirect("/group")


@router.get("/join")
def join_page(request: Request) -> HTMLResponse:
    return render(request, "join.html")


@router.post("/join")
def enter_code(code: str = Form("")) -> RedirectResponse:
    return redirect(f"/join/{groups.normalize_code(code) or 'none'}")


@router.get("/join/{code}")
def invite_page(request: Request, code: str, db: Session = Depends(get_db)) -> Response:
    """Show an invitation. This only ever shows the group's name."""
    visitor = visitor_key(request)
    if ratelimit.is_blocked(db, ratelimit.WRONG_CODE_PER_VISITOR, visitor):
        request.session["error"] = TOO_MANY_CODES
        return redirect("/join")
    group = groups.find_by_code(db, code)
    if group is None:
        ratelimit.record(db, ratelimit.WRONG_CODE_PER_VISITOR, visitor)
        request.session["error"] = "That code isn't valid. Check it and try again."
        return redirect("/join")

    user = session_user(request, db)
    if user is None:
        # Bring them back here after they sign up or log in.
        request.session["next"] = f"/join/{group.join_code}"
        return render(request, "invite.html", group=group)

    player = groups.player_for(db, group, user)
    if player and player.status == "approved":
        request.session["group_id"] = group.id
        return redirect("/")
    if player and player.status == "pending":
        request.session["message"] = (
            f"You've asked to join {group.name}. An admin needs to approve you."
        )
        return redirect("/groups")
    return render(request, "join_request.html", group=group, code=group.join_code, player=None)


@router.post("/join/{code}")
def request_to_join(
    request: Request,
    code: str,
    name: str = Form(""),
    primary: str = Form(""),
    secondary: str = Form(""),
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    visitor = visitor_key(request)
    if ratelimit.is_blocked(db, ratelimit.WRONG_CODE_PER_VISITOR, visitor):
        request.session["error"] = TOO_MANY_CODES
        return redirect("/join")
    group = groups.find_by_code(db, code)
    if group is None:
        ratelimit.record(db, ratelimit.WRONG_CODE_PER_VISITOR, visitor)
        request.session["error"] = "That code isn't valid. Check it and try again."
        return redirect("/join")
    try:
        groups.request_to_join(db, group, user, name, primary, secondary)
    except UserError as error:
        db.rollback()
        request.session["error"] = str(error)
        return redirect(f"/join/{group.join_code}")
    request.session["message"] = f"Request sent. An admin of {group.name} needs to approve you."
    return redirect("/groups")


# Attendance and teams


@router.post("/attendance")
def attendance(
    request: Request,
    status: str = Form(""),
    membership: Membership = Depends(require_member),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        games.set_attendance(
            db, games.current_game(db, membership.group), membership.player, status
        )
    except UserError as error:
        request.session["error"] = str(error)
    else:
        request.session["message"] = f"You're {status}."
    return redirect("/")


@router.post("/teams")
def make_teams(
    request: Request,
    membership: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        games.make_teams(db, games.current_game(db, membership.group))
    except UserError as error:
        request.session["error"] = str(error)
    else:
        request.session["message"] = "Teams made."
    return redirect("/#teams")


# Ratings


@router.get("/ratings")
def ratings_page(
    request: Request,
    membership: Membership = Depends(require_member),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    if not membership.group.has_ratings:
        return render(request, "ratings_upgrade.html", group=membership.group)
    others = [
        player
        for player in games.approved_players(db, membership.group)
        if player.id != membership.player.id
    ]
    mine = ratings.my_ratings(
        db, rating_secret(request), membership.player, [player.id for player in others]
    )
    return render(
        request,
        "ratings.html",
        group=membership.group,
        others=others,
        mine=mine,
        scores=range(ratings.MIN_SCORE, ratings.MAX_SCORE + 1),
        min_ratings=ratings.MIN_RATINGS,
    )


@router.post("/ratings")
def save_ratings(
    request: Request,
    form=Depends(form_data),
    membership: Membership = Depends(require_member),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        scores = {
            int(key.removeprefix("score_")): int(value)
            for key, value in form.items()
            if key.startswith("score_")
        }
    except ValueError:
        request.session["error"] = "Ratings go from 1 to 5."
        return redirect("/ratings")
    try:
        count = ratings.save_ratings(db, rating_secret(request), membership.player, scores)
    except UserError as error:
        request.session["error"] = str(error)
    else:
        request.session["message"] = "Ratings saved." if count else "Choose at least one rating."
    return redirect("/ratings")


# The group page


@router.get("/group")
def group_page(
    request: Request,
    membership: Membership = Depends(require_member),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = membership.group
    url = f"{base_url(request)}/join/{groups.format_code(group.join_code)}"
    return render(
        request,
        "group.html",
        group=group,
        player=membership.player,
        is_admin=membership.player.role == "admin",
        players=games.approved_players(db, group),
        group_code=groups.format_code(group.join_code),
        invite_url=url,
        whatsapp_url="https://wa.me/?text=" + quote(f"Join {group.name}: {url}", safe=""),
    )


@router.get("/group/configure")
def configure_page(
    request: Request,
    membership: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
) -> HTMLResponse:
    group = membership.group
    players = games.approved_players(db, group)
    return render(
        request,
        "group_configure.html",
        **GROUP_FIELD_OPTIONS,
        group=group,
        player=membership.player,
        players=players,
        requests=groups.pending_requests(db, group),
        averages=ratings.averages(db, [p.id for p in players]) if group.has_ratings else {},
        min_ratings=ratings.MIN_RATINGS,
        current_name=group.name,
        current_weekday=group.game_weekday,
        current_timezone=group.timezone,
    )


@router.post("/group/profile")
def update_profile(
    request: Request,
    name: str = Form(""),
    primary: str = Form(""),
    secondary: str = Form(""),
    membership: Membership = Depends(require_member),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        groups.update_profile(db, membership.player, name, primary, secondary)
    except UserError as error:
        db.rollback()
        request.session["error"] = str(error)
    else:
        request.session["message"] = "Your details are saved."
    return redirect("/group")


@router.post("/group/leave")
def leave_group(
    request: Request,
    membership: Membership = Depends(require_member),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        groups.leave_group(db, rating_secret(request), membership.player)
    except UserError as error:
        db.rollback()
        request.session["error"] = str(error)
        return redirect("/group")
    request.session.pop("group_id", None)
    request.session["message"] = f"You've left {membership.group.name}."
    return redirect("/groups")


@router.post("/group/requests/{player_id}/approve")
def approve_request(
    request: Request,
    player_id: int,
    membership: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        player = groups.approve_request(db, membership.group, player_id)
    except UserError as error:
        request.session["error"] = str(error)
    else:
        request.session["message"] = f"{player.name} is in the group."
    return redirect("/group/configure")


@router.post("/group/requests/{player_id}/decline")
def decline_request(
    request: Request,
    player_id: int,
    membership: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        player = groups.decline_request(db, membership.group, player_id)
    except UserError as error:
        request.session["error"] = str(error)
    else:
        request.session["message"] = f"Declined {player.name}."
    return redirect("/group/configure")


@router.post("/group/players/{player_id}/role")
def set_role(
    request: Request,
    player_id: int,
    role: str = Form(""),
    membership: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        player = groups.set_role(db, membership.group, player_id, role)
    except UserError as error:
        request.session["error"] = str(error)
    else:
        label = "an admin" if role == "admin" else "a regular member"
        request.session["message"] = f"{player.name} is now {label}."
    return redirect("/group/configure")


@router.post("/group/players/{player_id}/remove")
def remove_player(
    request: Request,
    player_id: int,
    membership: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        player = groups.remove_player(db, rating_secret(request), membership.group, player_id)
    except UserError as error:
        db.rollback()
        request.session["error"] = str(error)
    else:
        request.session["message"] = f"Removed {player.name}."
    return redirect("/group/configure")


@router.post("/group/settings")
def update_group(
    request: Request,
    name: str = Form(""),
    weekday: str = Form(""),
    timezone: str = Form(""),
    membership: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        groups.update_group(db, membership.group, name, weekday, timezone)
    except UserError as error:
        db.rollback()
        request.session["error"] = str(error)
    else:
        request.session["message"] = "Group saved."
    return redirect("/group/configure")


@router.post("/group/code")
def replace_code(
    request: Request,
    membership: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    groups.replace_code(db, membership.group)
    request.session["message"] = "Group code replaced. The old code and invite link no longer work."
    return redirect("/group/configure")


@router.post("/group/delete")
def delete_group(
    request: Request,
    confirmation: str = Form(""),
    membership: Membership = Depends(require_admin),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    name = membership.group.name
    try:
        groups.delete_group(db, membership.group, confirmation)
    except UserError as error:
        request.session["error"] = str(error)
        return redirect("/group/configure")
    request.session.pop("group_id", None)
    request.session["message"] = f"Deleted {name}."
    return redirect("/groups")
