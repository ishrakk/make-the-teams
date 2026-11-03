"""Pages, form handlers and health checks. Rules live in app/games/service.py."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Game
from app.games import service
from app.games.service import GameError
from app.web.auth import require_admin, require_member, role_for_passcode

router = APIRouter()
templates = Jinja2Templates(directory=Path(__file__).parent / "templates")


def get_db(request: Request) -> Iterator[Session]:
    with request.app.state.session_factory() as session:
        yield session


def current_game(request: Request, db: Session) -> Game:
    settings = request.app.state.settings
    today = datetime.now(ZoneInfo(settings.timezone)).date()
    return service.get_or_create_game(db, service.next_game_date(today, settings.game_weekday))


def render(request: Request, template: str, status_code: int = 200, **context) -> HTMLResponse:
    context["message"] = request.session.pop("message", None)
    context["error"] = request.session.pop("error", None)
    context["is_admin"] = request.session.get("role") == "admin"
    context["signed_in"] = "role" in request.session
    context["position_labels"] = service.POSITION_LABELS
    return templates.TemplateResponse(request, template, context, status_code=status_code)


def redirect(path: str) -> RedirectResponse:
    return RedirectResponse(path, status_code=303)


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


# Signing in


@router.get("/login")
def login_page(request: Request) -> HTMLResponse:
    return render(request, "login.html")


@router.post("/login")
def login(request: Request, passcode: str = Form("")) -> RedirectResponse:
    role = role_for_passcode(passcode, request.app.state.settings)
    if role is None:
        request.session["error"] = "That passcode isn't right. Check the WhatsApp group for it."
        return redirect("/login")
    request.session["role"] = role
    return redirect("/")


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    request.session.clear()
    return redirect("/login")


# The game page


@router.get("/", dependencies=[Depends(require_member)])
def game_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    view = service.game_view(db, current_game(request, db))
    return render(
        request,
        "game.html",
        view=view,
        game_date=service.format_game_date(view.game.game_date),
        players=service.active_players(db),
        selected_player_id=request.session.get("player_id"),
    )


@router.post("/rsvp", dependencies=[Depends(require_member)])
def rsvp(
    request: Request,
    player_id: int = Form(0),
    status: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        player = service.set_rsvp(db, current_game(request, db), player_id, status)
    except GameError as error:
        request.session["error"] = str(error)
    else:
        request.session["player_id"] = player.id
        request.session["message"] = f"{player.name} is {status}."
    return redirect("/")


@router.post("/teams", dependencies=[Depends(require_admin)])
def make_teams(request: Request, db: Session = Depends(get_db)) -> RedirectResponse:
    try:
        service.make_teams(db, current_game(request, db))
    except GameError as error:
        request.session["error"] = str(error)
    else:
        request.session["message"] = "Teams made."
    return redirect("/#teams")


# Players


@router.get("/players", dependencies=[Depends(require_member)])
def players_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(request, "players.html", players=service.active_players(db))


@router.post("/players", dependencies=[Depends(require_member)])
def add_player(
    request: Request,
    name: str = Form(""),
    primary: str = Form(""),
    secondary: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        player = service.add_player(db, name, primary, secondary)
    except GameError as error:
        request.session["error"] = str(error)
        return redirect("/players")
    request.session["player_id"] = player.id
    request.session["message"] = f"Added {player.name}."
    return redirect("/")


@router.get("/players/{player_id}", dependencies=[Depends(require_member)])
def edit_player_page(request: Request, player_id: int, db: Session = Depends(get_db)) -> Response:
    try:
        player = service.get_active_player(db, player_id)
    except GameError as error:
        request.session["error"] = str(error)
        return redirect("/players")
    return render(request, "player_edit.html", player=player)


@router.post("/players/{player_id}", dependencies=[Depends(require_member)])
def update_player(
    request: Request,
    player_id: int,
    name: str = Form(""),
    primary: str = Form(""),
    secondary: str = Form(""),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    try:
        service.update_player(db, player_id, name, primary, secondary)
    except GameError as error:
        request.session["error"] = str(error)
        return redirect(f"/players/{player_id}")
    request.session["message"] = "Player saved."
    return redirect("/players")


@router.post("/players/{player_id}/remove", dependencies=[Depends(require_admin)])
def remove_player(
    request: Request, player_id: int, db: Session = Depends(get_db)
) -> RedirectResponse:
    try:
        service.remove_player(db, player_id)
    except GameError as error:
        request.session["error"] = str(error)
    else:
        request.session["message"] = "Player removed."
    return redirect("/players")
