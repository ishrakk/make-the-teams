"""Tests that use the site the way a browser does."""

from __future__ import annotations

from tests.conftest import ADMIN_PASSCODE


def add_players(client, count=4):
    for index in range(count):
        response = client.post("/players", data={"name": f"Player {index}", "primary": "MID"})
        assert response.status_code == 303
    client.get("/")


def rsvp_all(client, count=4):
    for player_id in range(1, count + 1):
        client.post("/rsvp", data={"player_id": player_id, "status": "in"})


def test_health_checks_need_no_sign_in(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    assert client.get("/readyz").json() == {"status": "ok"}


def test_every_page_requires_sign_in(client):
    for path in ("/", "/players", "/players/1"):
        response = client.get(path)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"


def test_forms_require_sign_in(client):
    for path in ("/rsvp", "/players", "/teams", "/players/1", "/players/1/remove"):
        assert client.post(path, data={}).status_code == 303


def test_wrong_passcode_does_not_sign_in(client):
    client.post("/login", data={"passcode": "wrong"})
    assert client.get("/").status_code == 303
    assert "isn&#39;t right" in client.get("/login").text


def test_session_cookie_is_lax_and_http_only(client):
    response = client.post("/login", data={"passcode": ADMIN_PASSCODE})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_sign_out(member):
    member.post("/logout")
    assert member.get("/").status_code == 303


def test_full_journey_from_rsvp_to_teams(admin):
    add_players(admin)
    rsvp_all(admin)
    page = admin.get("/")
    assert "In (4)" in page.text
    assert "Make teams from 4 players" in page.text

    assert admin.post("/teams").headers["location"] == "/#teams"
    page = admin.get("/")
    assert "Team A" in page.text and "Team B" in page.text
    assert "Share on WhatsApp" in page.text
    assert "Reshuffle teams" in page.text


def test_members_cannot_make_teams_or_remove_players(member):
    add_players(member)
    assert "Make teams" not in member.get("/").text
    assert member.post("/teams").status_code == 403
    assert member.post("/players/1/remove").status_code == 403
    assert "Remove" not in member.get("/players/1").text


def test_making_teams_with_too_few_players_shows_a_message(admin):
    admin.post("/teams")
    assert "at least 2 players" in admin.get("/").text


def test_invalid_rsvp_shows_a_message(member):
    member.post("/rsvp", data={"player_id": 99, "status": "in"})
    assert "isn&#39;t on the list" in member.get("/").text


def test_player_names_are_escaped(member):
    member.post("/players", data={"name": "<script>alert(1)</script>", "primary": "MID"})
    page = member.get("/players").text
    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page


def test_edit_a_player(member):
    add_players(member, 1)
    member.post("/players/1", data={"name": "Renamed", "primary": "GK", "secondary": "DEF"})
    assert "Renamed" in member.get("/players").text


def test_rsvp_remembers_who_you_are(member):
    add_players(member, 2)
    member.post("/rsvp", data={"player_id": 2, "status": "in"})
    assert '<option value="2" selected>' in member.get("/").text
