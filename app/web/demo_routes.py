"""One-tap switching between test users. Only added to the app when DEMO_MODE is on."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.db.models import User
from app.demo.seed import DEMO_PASSWORD, demo_accounts, is_demo_email
from app.web.auth import get_db, sign_in
from app.web.routes import render

router = APIRouter()


@router.get("/demo")
def demo_page(request: Request, db: Session = Depends(get_db)) -> HTMLResponse:
    return render(request, "demo.html", accounts=demo_accounts(db), password=DEMO_PASSWORD)


@router.post("/demo/switch/{user_id}")
def switch_user(request: Request, user_id: int, db: Session = Depends(get_db)) -> RedirectResponse:
    user = db.get(User, user_id)
    # Real accounts can't be reached this way, even in demo mode.
    if user is None or not is_demo_email(user.email):
        raise HTTPException(status_code=404)
    request.session.pop("next", None)
    sign_in(request, user)
    request.session["demo_email"] = user.email
    return RedirectResponse("/groups", status_code=303)
