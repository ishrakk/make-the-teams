"""Tests for the journey into a group, what admins can do, and keeping groups separate."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app import ratelimit
from app.db.models import Group, Player
from app.groups import service as groups
from app.web.auth import visitor_key
from app.web.main import create_app
from tests.conftest import PASSWORD, Site, make_settings


def test_full_journey_from_sign_up_to_teams(site):
    # An organizer signs up and creates a group.
    admin, group = site.group_with_admin()
    assert "Invite your friends" in admin.get("/group").text

    # A friend follows the invite link while signed out, and signs up.
    friend = site.browser()
    invite = friend.get(f"/join/{groups.format_code(group.join_code)}")
    assert "Join Saturday Crew" in invite.text
    response = friend.post("/signup", data={"email": "f@example.com", "password": PASSWORD})
    assert response.headers["location"] == f"/join/{group.join_code}"

    # They ask to join, and can't see the group until an admin approves them.
    friend.post(f"/join/{group.join_code}", data={"name": "Friend", "primary": "GK"})
    assert "Waiting for an admin to approve you" in friend.get("/groups").text
    assert friend.get("/").headers["location"] == "/groups"
    assert friend.get("/group").headers["location"] == "/groups"

    # The admin sees the request and approves it.
    page = admin.get("/group/configure").text
    assert "Waiting for approval (1)" in page and "Friend" in page
    friend_player = site.player(group, "Friend")
    admin.post(f"/group/requests/{friend_player.id}/approve")

    # The friend votes, and the admin votes and makes teams.
    assert "Are you coming, Friend?" in friend.get("/").text
    friend.post("/attendance", data={"status": "in"})
    assert "You&#39;re in" in friend.get("/").text
    admin.post("/attendance", data={"status": "in"})
    admin.post("/teams")
    page = friend.get("/").text
    assert "Team A" in page and "Team B" in page and "Friend" in page
    assert "Reshuffle teams" not in page
    assert "Reshuffle teams" in admin.get("/").text


def test_home_page_is_public_and_other_pages_need_sign_in(site):
    browser = site.browser()
    assert "Fair teams" in browser.get("/").text
    for path in ("/group", "/ratings", "/account", "/groups", "/groups/new"):
        response = browser.get(path)
        assert response.status_code == 303 and response.headers["location"] == "/login"


def test_forms_need_sign_in(site):
    browser = site.browser()
    for path in ("/attendance", "/teams", "/ratings", "/group/code", "/group/delete", "/groups"):
        assert browser.post(path, data={}).headers["location"] == "/login"


def test_health_checks_need_no_sign_in(site):
    browser = site.browser()
    assert browser.get("/healthz").json() == {"status": "ok"}
    assert browser.get("/readyz").json() == {"status": "ok"}


def test_code_works_with_any_spacing_or_case(site):
    _, group = site.group_with_admin()
    code = groups.format_code(group.join_code).lower().replace("-", " ")
    browser = site.person("f@example.com")
    response = browser.post("/join", data={"code": code})
    assert browser.get(response.headers["location"]).status_code == 200


def test_a_wrong_code_shows_a_message(site):
    browser = site.person("f@example.com")
    location = browser.post("/join", data={"code": "WRONG"}).headers["location"]
    browser.get(location)
    assert "code isn&#39;t valid" in browser.get("/join").text


def test_repeated_wrong_codes_are_blocked_even_with_a_right_one(site):
    _, group = site.group_with_admin()
    browser = site.person("f@example.com")
    for _ in range(ratelimit.WRONG_CODE_PER_VISITOR.max_count):
        browser.get("/join/WRONGCODE")
    assert browser.get(f"/join/{group.join_code}").status_code == 303
    assert "Too many wrong codes" in browser.get("/join").text


def test_too_many_new_groups_from_one_visitor_are_blocked(site, db):
    browser = site.person("a@example.com")
    data = {
        "weekday": "5",
        "timezone": "America/New_York",
        "player_name": "Me",
        "primary": "MID",
    }
    for index in range(ratelimit.GROUPS_PER_VISITOR.max_count + 1):
        browser.post("/groups", data={**data, "name": f"Group {index}"})
    db.expire_all()
    assert len(list(db.scalars(select(Group)))) == ratelimit.GROUPS_PER_VISITOR.max_count


def test_invalid_group_details_are_rejected(site, db):
    browser = site.person("a@example.com")
    browser.post(
        "/groups",
        data={"name": "", "weekday": "5", "timezone": "UTC", "player_name": "Me", "primary": "MID"},
    )
    assert "Enter a group name" in browser.get("/groups/new").text
    browser.post(
        "/groups",
        data={
            "name": "X",
            "weekday": "9",
            "timezone": "UTC",
            "player_name": "Me",
            "primary": "MID",
        },
    )
    assert "Choose a game day" in browser.get("/groups/new").text
    db.expire_all()
    assert list(db.scalars(select(Group))) == []


def test_name_is_unique_within_a_group_but_not_across_groups(site):
    _, first = site.group_with_admin("a@example.com", "First")
    _, second = site.group_with_admin("b@example.com", "Second")
    browser = site.person("c@example.com")
    browser.post(f"/join/{first.join_code}", data={"name": "A", "primary": "MID"})
    assert "already uses the name" in browser.get(f"/join/{first.join_code}").text
    browser.post(f"/join/{second.join_code}", data={"name": "A", "primary": "MID"})
    assert site.player(second, "A").status == "pending"


def test_declined_person_can_ask_again_and_is_not_in_the_group(site):
    admin, group = site.group_with_admin()
    friend = site.ask_to_join(group, "f@example.com")
    player = site.player(group, "f")
    admin.post(f"/group/requests/{player.id}/decline")
    assert friend.get("/").headers["location"] == "/groups"
    friend.get("/groups")  # Clears the earlier "request sent" message.
    assert "Saturday Crew" not in friend.get("/groups").text
    friend.post(f"/join/{group.join_code}", data={"name": "f", "primary": "FWD"})
    assert site.player(group, "f").status == "pending"
    assert site.player(group, "f").id == player.id


def test_members_cannot_do_admin_actions(site):
    admin, group = site.group_with_admin()
    member = site.member(admin, group, "m@example.com")
    pending = site.ask_to_join(group, "p@example.com")
    pending_player = site.player(group, "p")
    admin_player = site.player(group, "admin")
    forbidden = [
        ("/teams", {}),
        (f"/group/requests/{pending_player.id}/approve", {}),
        (f"/group/requests/{pending_player.id}/decline", {}),
        (f"/group/players/{admin_player.id}/role", {"role": "member"}),
        (f"/group/players/{admin_player.id}/remove", {}),
        ("/group/settings", {"name": "Hacked", "weekday": "1", "timezone": "UTC"}),
        ("/group/code", {}),
        ("/group/delete", {"confirmation": "Saturday Crew"}),
    ]
    for path, data in forbidden:
        assert member.post(path, data=data).status_code == 403, path
        # Someone still waiting for approval isn't in the group at all.
        assert pending.post(path, data=data).headers["location"] == "/groups", path
    assert site.player(group, "p").status == "pending"
    site.db.refresh(group)
    assert group.name == "Saturday Crew"


def test_admin_of_one_group_has_no_power_in_another(site):
    admin_a, group_a = site.group_with_admin("a@example.com", "Group A")
    admin_b, group_b = site.group_with_admin("b@example.com", "Group B")
    site.ask_to_join(group_b, "pending@example.com")
    member_b = site.player(group_b, "b")
    pending_b = site.player(group_b, "pending")
    admin_a.post(f"/group/requests/{pending_b.id}/approve")
    admin_a.post(f"/group/players/{member_b.id}/remove")
    admin_a.post(f"/group/players/{member_b.id}/role", data={"role": "member"})
    assert site.player(group_b, "pending").status == "pending"
    assert site.player(group_b, "b").status == "approved"
    assert site.player(group_b, "b").role == "admin"


def test_you_cannot_open_a_group_you_are_not_in(site):
    _, group_b = site.group_with_admin("b@example.com", "Group B")
    admin_a, group_a = site.group_with_admin("a@example.com", "Group A")
    admin_a.post(f"/groups/{group_b.id}/open")
    page = admin_a.get("/").text
    assert "Group A" in page and "Group B" not in page


def test_groups_cannot_see_each_others_players(site):
    admin_a, group_a = site.group_with_admin("a@example.com", "Group A")
    admin_b, group_b = site.group_with_admin("b@example.com", "Group B")
    site.member(admin_b, group_b, "secret-player@example.com")
    for path in ("/", "/group", "/ratings"):
        assert "secret-player" not in admin_a.get(path).text


def test_one_person_can_be_in_two_groups_and_switch(site):
    admin_a, group_a = site.group_with_admin("a@example.com", "Group A")
    admin_b, group_b = site.group_with_admin("b@example.com", "Group B")
    both = site.member(admin_a, group_a, "both@example.com")
    both.post(f"/join/{group_b.join_code}", data={"name": "both", "primary": "GK"})
    player_b = site.player(group_b, "both")
    admin_b.post(f"/group/requests/{player_b.id}/approve")
    both.post(f"/groups/{group_b.id}/open")
    assert "Group B" in both.get("/").text
    both.post(f"/groups/{group_a.id}/open")
    assert "Group A" in both.get("/").text


def test_attendance_is_only_ever_for_yourself(site):
    admin, group = site.group_with_admin()
    member = site.member(admin, group, "m@example.com")
    other = site.player(group, "admin")
    member.post("/attendance", data={"status": "in", "player_id": other.id})
    page = admin.get("/").text
    assert "Are you coming, admin?" in page
    assert re.search(r"Attending <span>1</span>", page)
    assert re.search(r"Not responded <span>1</span>", page)


def test_group_needs_at_least_one_admin(site):
    admin, group = site.group_with_admin()
    admin_player = site.player(group, "admin")
    member = site.member(admin, group, "m@example.com")
    member_player = site.player(group, "m")
    admin.post("/group/leave")
    assert "needs at least one admin" in admin.get("/group").text
    admin.post(f"/group/players/{admin_player.id}/role", data={"role": "member"})
    assert "needs at least one admin" in admin.get("/group/configure").text
    admin.post(f"/group/players/{member_player.id}/role", data={"role": "admin"})
    admin.post("/group/leave")
    assert site.player(group, "admin").status == "removed"
    assert "Group settings" in member.get("/group/configure").text


def test_any_admin_can_approve(site):
    admin, group = site.group_with_admin()
    second = site.member(admin, group, "second@example.com")
    admin.post(f"/group/players/{site.player(group, 'second').id}/role", data={"role": "admin"})
    site.ask_to_join(group, "new@example.com")
    second.post(f"/group/requests/{site.player(group, 'new').id}/approve")
    assert site.player(group, "new").status == "approved"


def test_replacing_the_code_stops_the_old_one_but_keeps_members(site):
    admin, group = site.group_with_admin()
    member = site.member(admin, group, "m@example.com")
    old_code = group.join_code
    admin.post("/group/code")
    site.db.refresh(group)
    assert group.join_code != old_code
    assert site.person("new@example.com").get(f"/join/{old_code}").headers["location"] == "/join"
    assert "Are you coming" in member.get("/").text


def test_delete_group_needs_its_name_and_removes_everything(site, db):
    admin, group = site.group_with_admin()
    member = site.member(admin, group, "m@example.com")
    admin.post("/group/delete", data={"confirmation": "wrong"})
    db.expire_all()
    assert db.get(Group, group.id) is not None
    admin.post("/group/delete", data={"confirmation": "saturday crew"})
    db.expire_all()
    assert list(db.scalars(select(Group))) == []
    assert list(db.scalars(select(Player))) == []
    assert member.get("/").headers["location"] == "/groups"


def test_names_are_escaped(site):
    browser = site.person("a@example.com")
    browser.post(
        "/groups",
        data={
            "name": "<script>alert(1)</script>",
            "weekday": "5",
            "timezone": "America/New_York",
            "player_name": "<b>me</b>",
            "primary": "MID",
        },
    )
    page = browser.get("/group").text
    assert "<script>alert" not in page and "<b>me" not in page
    assert "&lt;script&gt;" in page


def test_security_headers(site):
    response = site.browser().get("/join")
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-robots-tag"] == "noindex"


@pytest.mark.parametrize(
    ("hops", "forwarded", "expected_same_as"),
    [
        (0, "9.9.9.9", "testclient"),  # No proxy: ignore the header.
        (1, "1.1.1.1", "1.1.1.1"),
        (1, "6.6.6.6, 1.1.1.1", "1.1.1.1"),  # A forged left entry is ignored.
        (2, "6.6.6.6, 1.1.1.1, 10.0.0.1", "1.1.1.1"),
    ],
)
def test_visitor_address_ignores_what_the_visitor_can_forge(
    database_url, hops, forwarded, expected_same_as
):
    from starlette.requests import Request

    app = create_app(make_settings(database_url, trusted_proxy_hops=hops))

    def key(header, client):
        scope = {
            "type": "http",
            "app": app,
            "headers": [(b"x-forwarded-for", header.encode())],
            "client": (client, 1),
        }
        return visitor_key(Request(scope))

    expected = key("x", expected_same_as) if hops == 0 else key(expected_same_as, "testclient")
    if hops == 2:
        expected = key(f"{expected_same_as}, 10.0.0.1", "testclient")
    assert key(forwarded, "testclient") == expected


def test_site_helper_is_not_shared_between_people(database_url, db):
    site = Site(create_app(make_settings(database_url)), db)
    first, second = site.person("1@example.com"), site.person("2@example.com")
    assert "1@example.com" in first.get("/account").text
    assert "2@example.com" in second.get("/account").text


def test_logging_in_shows_your_groups(site):
    site.group_with_admin("a@example.com", "Group A")
    browser = site.browser()
    response = browser.post("/login", data={"email": "a@example.com", "password": PASSWORD})
    assert response.headers["location"] == "/groups"
    page = browser.get("/groups").text
    assert "Group A" in page and "Next game:" in page


def test_groups_page_shows_every_group_with_your_answer_and_waiting_requests(site):
    admin_a, group_a = site.group_with_admin("a@example.com", "Group A")
    _, group_b = site.group_with_admin("b@example.com", "Group B")
    both = site.member(admin_a, group_a, "both@example.com")
    both.post("/attendance", data={"status": "in"})
    both.post(f"/join/{group_b.join_code}", data={"name": "both", "primary": "GK"})
    both.get("/groups")  # Clears the "request sent" message.
    page = both.get("/groups").text
    assert "Group A" in page and "1 attending, 0 declined, 1 not responded" in page
    assert "You&#39;re attending" in page or "You're attending" in page
    assert "Group B" in page and "Waiting for an admin to approve you" in page


def test_game_page_lists_every_player_with_their_answer(site):
    admin, group = site.group_with_admin()
    going = site.member(admin, group, "going@example.com")
    away = site.member(admin, group, "away@example.com")
    site.member(admin, group, "quiet@example.com")
    site.ask_to_join(group, "pending@example.com")
    going.post("/attendance", data={"status": "in"})
    away.post("/attendance", data={"status": "out"})
    page = going.get("/").text
    assert "Players (4)" in page
    assert "Attending <span>1</span>" in page
    assert "Declined <span>1</span>" in page
    assert "Not responded <span>2</span>" in page
    assert "pending" not in page
    attending, declined, not_responded = (
        page.index("Attending <span>"),
        page.index("Declined <span>"),
        page.index("Not responded <span>"),
    )
    assert attending < page.index("going", attending) < declined
    assert declined < page.index("away", declined) < not_responded
    assert not_responded < page.index("quiet", not_responded)


def test_game_page_shows_all_three_groups_even_when_empty(site):
    admin, _ = site.group_with_admin()
    page = admin.get("/").text
    assert "Attending <span>0</span>" in page
    assert "Declined <span>0</span>" in page
    assert "Not responded <span>1</span>" in page


def test_home_page_says_what_the_site_does_and_that_it_is_free(site):
    page = site.browser().get("/").text
    assert "free to join" in page and "How it works" in page and "Sign up free" in page
    assert "save time on the field and get to the game faster" in page


def test_only_admins_get_the_configure_option_and_page(site):
    admin, group = site.group_with_admin()
    member = site.member(admin, group, "m@example.com")
    assert "Configure group" in admin.get("/groups").text
    assert "Configure group" not in member.get("/groups").text
    assert admin.get("/group/configure").status_code == 200
    assert member.get("/group/configure").status_code == 403
    response = member.post(f"/groups/{group.id}/open", data={"to": "configure"})
    assert member.get(response.headers["location"]).status_code == 403


def test_details_page_has_no_admin_controls(site):
    admin, group = site.group_with_admin()
    site.ask_to_join(group, "waiting@example.com")
    page = admin.get("/group").text
    assert "Invite your friends" in page and "Your details" in page
    for control in ("Group settings", "Delete group", "Approve", "Replace group code"):
        assert control not in page
    assert "Configure group" in page


def test_configure_card_opens_that_group_and_counts_requests(site):
    admin, group_a = site.group_with_admin("a@example.com", "Group A")
    admin.post(
        "/groups",
        data={
            "name": "Group B",
            "weekday": "2",
            "timezone": "America/New_York",
            "player_name": "a",
            "primary": "MID",
        },
    )
    site.ask_to_join(group_a, "new@example.com")
    assert "Configure group (1 waiting for approval)" in admin.get("/groups").text
    response = admin.post(f"/groups/{group_a.id}/open", data={"to": "configure"})
    assert response.headers["location"] == "/group/configure"
    assert "Configure Group A" in admin.get("/group/configure").text


def test_opening_a_group_you_are_not_in_never_shows_your_other_group_as_it(site):
    _, other = site.group_with_admin("b@example.com", "Group B")
    admin, _ = site.group_with_admin("a@example.com", "Group A")
    response = admin.post(f"/groups/{other.id}/open", data={"to": "configure"})
    assert response.headers["location"] == "/groups"
    assert "You&#39;re not in that group" in admin.get("/groups").text


def test_unknown_destination_goes_to_the_game_page(site):
    admin, group = site.group_with_admin()
    response = admin.post(f"/groups/{group.id}/open", data={"to": "https://evil.test"})
    assert response.headers["location"] == "/"


@pytest.mark.parametrize(
    ("path", "active"),
    [
        ("/groups", "nav-groups"),
        ("/", "nav-week"),
        ("/ratings", "nav-ratings"),
        ("/account", "nav-account"),
        ("/group", "nav-groups"),
        ("/group/configure", "nav-groups"),
    ],
)
def test_menu_highlights_the_current_section(site, path, active):
    admin, _ = site.group_with_admin()
    page = admin.get(path).text
    assert re.findall(r"nav-link (nav-\w+) is-active", page) == [active]
