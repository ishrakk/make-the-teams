"""Builds the FastAPI app. Run with: uvicorn --factory app.web.main:create_app"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import Settings
from app.db.session import make_session_factory
from app.web.auth import SignInRequired
from app.web.routes import router

NINETY_DAYS = 90 * 24 * 60 * 60


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Make the Teams", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings
    app.state.session_factory = make_session_factory(settings.database_url)

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        max_age=NINETY_DAYS,
        same_site="lax",  # Other sites can't submit forms using this cookie.
        https_only=settings.secure_cookies,
    )

    @app.exception_handler(SignInRequired)
    def go_to_login(_: Request, __: SignInRequired) -> RedirectResponse:
        return RedirectResponse("/login", status_code=303)

    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")
    app.include_router(router)
    return app
