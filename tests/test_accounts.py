"""Tests for signing up, signing in and resetting passwords."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app import ratelimit
from app.accounts import email as account_email
from app.accounts import service as accounts
from app.db.models import PasswordReset, User
from app.web.main import create_app
from tests.conftest import PASSWORD, Site, make_settings


def login(browser, email, password=PASSWORD):
    return browser.post("/login", data={"email": email, "password": password})


def is_signed_in(browser) -> bool:
    return browser.get("/account").status_code == 200


def test_sign_up_signs_you_in(site):
    assert is_signed_in(site.person("a@example.com"))


def test_passwords_are_stored_only_as_argon2_hashes(site, db):
    site.person("a@example.com")
    user = db.scalars(select(User)).one()
    assert user.password_hash.startswith("$argon2id$")
    assert PASSWORD not in user.password_hash


def test_email_is_case_insensitive_and_unique(site):
    site.person("Sam@Example.com")
    browser = site.browser()
    browser.post("/signup", data={"email": "sam@example.com", "password": PASSWORD})
    assert not is_signed_in(browser)
    assert "already has an account" in browser.get("/signup").text
    login(browser, "SAM@example.com")
    assert is_signed_in(browser)


@pytest.mark.parametrize(
    ("email", "password", "message"),
    [
        ("not-an-email", PASSWORD, "valid email"),
        ("a@example.com", "short", "at least 10"),
        ("a@example.com", "x" * 129, "up to 128"),
    ],
)
def test_invalid_sign_ups_are_rejected(site, email, password, message):
    browser = site.browser()
    browser.post("/signup", data={"email": email, "password": password})
    assert message in browser.get("/signup").text
    assert not is_signed_in(browser)


def test_wrong_password_does_not_sign_in_and_gives_the_same_message(site):
    site.person("a@example.com")
    known, unknown = site.browser(), site.browser()
    login(known, "a@example.com", "wrong-password")
    login(unknown, "nobody@example.com", "wrong-password")
    message = "That email and password don&#39;t match."
    assert message in known.get("/login").text
    assert message in unknown.get("/login").text


def test_log_out(site):
    browser = site.person("a@example.com")
    browser.post("/logout")
    assert not is_signed_in(browser)


def test_session_cookie_is_lax_and_http_only(site):
    response = site.browser().post("/signup", data={"email": "a@example.com", "password": PASSWORD})
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie


def test_secure_cookie_flag_is_on_by_default(database_url, db):
    app = create_app(make_settings(database_url, secure_cookies=True))
    response = (
        Site(app, db)
        .browser()
        .post("/signup", data={"email": "a@example.com", "password": PASSWORD})
    )
    assert "secure" in response.headers["set-cookie"].lower()


def test_repeated_wrong_passwords_are_blocked_even_with_the_right_one(site):
    site.person("a@example.com")
    browser = site.browser()
    for _ in range(ratelimit.WRONG_PASSWORD_PER_EMAIL.max_count):
        login(browser, "a@example.com", "wrong-password")
    login(browser, "a@example.com")
    assert not is_signed_in(browser)
    assert "Too many wrong passwords" in browser.get("/login").text


def test_too_many_sign_ups_from_one_visitor_are_blocked(site):
    for index in range(ratelimit.SIGNUP_PER_VISITOR.max_count):
        site.person(f"user{index}@example.com")
    browser = site.browser()
    browser.post("/signup", data={"email": "extra@example.com", "password": PASSWORD})
    assert not is_signed_in(browser)


def test_changing_password_signs_out_other_devices_only(site):
    phone = site.person("a@example.com")
    laptop = site.browser()
    login(laptop, "a@example.com")
    phone.post(
        "/account/password",
        data={"current_password": PASSWORD, "new_password": "a-brand-new-password"},
    )
    assert is_signed_in(phone)
    assert not is_signed_in(laptop)
    login(laptop, "a@example.com", "a-brand-new-password")
    assert is_signed_in(laptop)


def test_changing_password_needs_the_current_one(site):
    browser = site.person("a@example.com")
    browser.post(
        "/account/password", data={"current_password": "wrong", "new_password": "new-password-1"}
    )
    assert "current password isn" in browser.get("/account").text
    browser.post("/logout")
    login(browser, "a@example.com")
    assert is_signed_in(browser)


@pytest.fixture
def sent(monkeypatch):
    emails = []
    monkeypatch.setattr(
        account_email,
        "send_password_reset",
        lambda settings, to, link: emails.append((to, link)),
    )
    return emails


def reset_path(link: str) -> str:
    return re.sub(r"^https://teams\.test", "", link)


def test_password_reset_changes_the_password_once(site, sent):
    site.person("a@example.com")
    browser = site.browser()
    browser.post("/forgot", data={"email": "a@example.com"})
    [(to, link)] = sent
    assert to == "a@example.com" and link.startswith("https://teams.test/reset/")
    path = reset_path(link)
    assert browser.get(path).status_code == 200
    browser.post(path, data={"password": "a-brand-new-password"})
    login(browser, "a@example.com", "a-brand-new-password")
    assert is_signed_in(browser)
    assert site.browser().get(path).status_code == 303  # The link only works once.


def test_reset_signs_out_existing_sessions(site, sent):
    phone = site.person("a@example.com")
    browser = site.browser()
    browser.post("/forgot", data={"email": "a@example.com"})
    browser.post(reset_path(sent[0][1]), data={"password": "a-brand-new-password"})
    assert not is_signed_in(phone)


def test_reset_token_is_stored_only_as_a_hash(site, sent, db):
    site.person("a@example.com")
    site.browser().post("/forgot", data={"email": "a@example.com"})
    token = sent[0][1].rsplit("/", 1)[-1]
    stored = db.scalars(select(PasswordReset)).one()
    assert stored.token_hash != token and token not in stored.token_hash


def test_forgot_password_does_not_reveal_who_has_an_account(site, sent):
    site.person("a@example.com")
    known, unknown = site.browser(), site.browser()
    known.post("/forgot", data={"email": "a@example.com"})
    unknown.post("/forgot", data={"email": "nobody@example.com"})
    message = "If that email has an account"
    assert message in known.get("/login").text and message in unknown.get("/login").text
    assert len(sent) == 1


def test_reset_emails_to_one_address_are_limited(site, sent):
    site.person("a@example.com")
    browser = site.browser()
    for _ in range(ratelimit.RESET_PER_EMAIL.max_count + 2):
        browser.post("/forgot", data={"email": "a@example.com"})
    assert len(sent) == ratelimit.RESET_PER_EMAIL.max_count


def test_expired_reset_links_do_not_work(site, sent, db):
    from datetime import UTC, datetime, timedelta

    site.person("a@example.com")
    browser = site.browser()
    browser.post("/forgot", data={"email": "a@example.com"})
    db.scalars(select(PasswordReset)).one().expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    assert browser.get(reset_path(sent[0][1])).status_code == 303


def test_reset_is_turned_off_without_email_settings(database_url, db):
    app = create_app(make_settings(database_url, log_emails=False))
    browser = Site(app, db).browser()
    assert "can't send email" in browser.get("/forgot").text
    assert "Forgot your password" not in browser.get("/login").text


def test_reset_email_is_sent_over_smtp_with_tls(monkeypatch, database_url):
    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def starttls(self):
            calls.append(("starttls",))

        def login(self, username, password):
            calls.append(("login", username))

        def send_message(self, message):
            calls.append(("send", message["To"], message.get_content()))

    monkeypatch.setattr(account_email.smtplib, "SMTP", FakeSMTP)
    settings = make_settings(
        database_url,
        log_emails=False,
        smtp_host="smtp.test",
        smtp_username="user",
        smtp_password="secret",
    )
    account_email.send_password_reset(settings, "a@example.com", "https://teams.test/reset/abc")
    assert calls[0] == ("connect", "smtp.test", 587)
    assert calls[1] == ("starttls",)
    assert calls[2] == ("login", "user")
    assert calls[3][1] == "a@example.com" and "https://teams.test/reset/abc" in calls[3][2]


def test_delete_account_needs_the_password(site, db):
    browser = site.person("a@example.com")
    browser.post("/account/delete", data={"password": "wrong"})
    db.expire_all()
    assert db.scalars(select(User)).one().email == "a@example.com"
    browser.post("/account/delete", data={"password": PASSWORD})
    db.expire_all()
    assert list(db.scalars(select(User))) == []
    assert not is_signed_in(browser)


def test_only_admin_must_hand_over_before_deleting_their_account(site, db):
    admin, _ = site.group_with_admin()
    admin.post("/account/delete", data={"password": PASSWORD})
    assert "only admin of Saturday Crew" in admin.get("/account").text
    db.expire_all()
    assert len(list(db.scalars(select(User)))) == 1


def test_dummy_hash_check_runs_for_unknown_emails(monkeypatch, db, database_url):
    checked = []
    monkeypatch.setattr(
        accounts, "_password_matches", lambda stored, password: checked.append(stored) or False
    )
    assert accounts.authenticate(db, "nobody@example.com", "whatever") is None
    assert checked == [accounts._DUMMY_HASH]
