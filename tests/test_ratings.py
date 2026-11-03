"""Tests that ratings are anonymous, limited to the group and only seen by admins."""

from __future__ import annotations

from sqlalchemy import inspect, select

from app.db.models import Rating
from app.ratings import service as ratings
from tests.conftest import RATING_SECRET


def setup(site):
    admin, group = site.group_with_admin()
    alice = site.member(admin, group, "alice@example.com")
    bob = site.member(admin, group, "bob@example.com")
    cara = site.member(admin, group, "cara@example.com")
    return admin, group, alice, bob, cara


def rate(browser, player, score):
    return browser.post("/ratings", data={f"score_{player.id}": str(score)})


def test_rating_table_has_no_column_identifying_the_rater(site):
    columns = {column.name for column in inspect(Rating).columns}
    assert columns == {"rated_player_id", "rater_tag", "score"}


def test_a_raters_tags_cannot_be_linked_without_the_key(site, db):
    admin, group, alice, bob, cara = setup(site)
    bob_player = site.player(group, "bob")
    cara_player = site.player(group, "cara")
    rate(alice, bob_player, 4)
    rate(alice, cara_player, 2)
    db.expire_all()
    tags = list(db.scalars(select(Rating.rater_tag)))
    assert len(set(tags)) == 2
    alice_player = site.player(group, "alice")
    assert str(alice_player.id) not in tags
    assert ratings.rater_tag("a-different-key" * 3, alice_player.id, bob_player.id) not in tags


def test_rating_again_replaces_the_earlier_score(site, db):
    admin, group, alice, bob, cara = setup(site)
    bob_player = site.player(group, "bob")
    rate(alice, bob_player, 2)
    rate(alice, bob_player, 5)
    db.expire_all()
    assert list(db.scalars(select(Rating.score))) == [5]


def test_raters_see_their_own_earlier_score(site):
    admin, group, alice, bob, cara = setup(site)
    bob_player = site.player(group, "bob")
    rate(alice, bob_player, 3)
    assert f'name="score_{bob_player.id}" value="3" checked' in alice.get("/ratings").text
    assert "checked" not in cara.get("/ratings").text


def test_you_cannot_rate_yourself(site, db):
    admin, group, alice, bob, cara = setup(site)
    rate(alice, site.player(group, "alice"), 5)
    db.expire_all()
    assert list(db.scalars(select(Rating))) == []
    assert "only rate other players" in alice.get("/ratings").text


def test_scores_outside_one_to_five_are_rejected(site, db):
    admin, group, alice, bob, cara = setup(site)
    bob_player = site.player(group, "bob")
    for score in ("0", "6", "abc"):
        alice.post("/ratings", data={f"score_{bob_player.id}": score})
    db.expire_all()
    assert list(db.scalars(select(Rating))) == []


def test_you_cannot_rate_someone_in_another_group(site, db):
    admin, group, alice, bob, cara = setup(site)
    _, other = site.group_with_admin("other@example.com", "Other Group")
    outsider = site.player(other, "other")
    rate(alice, outsider, 1)
    db.expire_all()
    assert list(db.scalars(select(Rating))) == []


def test_pending_players_cannot_rate_or_be_rated(site, db):
    admin, group, alice, bob, cara = setup(site)
    pending = site.ask_to_join(group, "newcomer@example.com")
    newcomer = site.player(group, "newcomer")
    bob_player = site.player(group, "bob")
    assert rate(pending, bob_player, 1).status_code == 303
    rate(alice, newcomer, 1)
    db.expire_all()
    assert list(db.scalars(select(Rating))) == []


def test_average_is_hidden_until_enough_people_have_rated(site):
    admin, group, alice, bob, cara = setup(site)
    bob_player = site.player(group, "bob")
    rate(alice, bob_player, 5)
    rate(cara, bob_player, 3)
    assert "Rating 4.0" not in admin.get("/group/configure").text
    rate(admin, bob_player, 4)
    assert "Rating 4.0 from 3 people" in admin.get("/group/configure").text


def test_only_admins_see_averages(site):
    admin, group, alice, bob, cara = setup(site)
    bob_player = site.player(group, "bob")
    for rater in (admin, alice, cara):
        rate(rater, bob_player, 4)
    for member in (alice, bob, cara):
        page = member.get("/group").text
        assert "Rating 4.0" not in page and "Fewer than" not in page
        assert member.get("/group/configure").status_code == 403
    assert "Rating 4.0" not in admin.get("/group").text


def test_leaving_a_group_deletes_ratings_given_and_received(site, db):
    admin, group, alice, bob, cara = setup(site)
    alice_player = site.player(group, "alice")
    bob_player = site.player(group, "bob")
    rate(alice, bob_player, 5)
    rate(bob, alice_player, 5)
    rate(cara, bob_player, 2)
    alice.post("/group/leave")
    db.expire_all()
    assert list(db.scalars(select(Rating.score))) == [2]


def test_forget_uses_the_same_tags_as_saving(site, db):
    admin, group, alice, bob, cara = setup(site)
    alice_player = site.player(group, "alice")
    bob_player = site.player(group, "bob")
    rate(alice, bob_player, 5)
    db.expire_all()
    expected = ratings.rater_tag(RATING_SECRET, alice_player.id, bob_player.id)
    assert list(db.scalars(select(Rating.rater_tag))) == [expected]


def rated_game(site):
    """Two keepers and four outfield players, all rated by everyone, with teams made."""
    admin, group = site.group_with_admin()
    people = {"admin": admin}
    for name, position in [
        ("keeper2", "GK"),
        ("alice", "DEF"),
        ("bob", "DEF"),
        ("cara", "FWD"),
        ("dan", "FWD"),
    ]:
        people[name] = site.member(admin, group, f"{name}@example.com", position)
    for rater_name, rater in people.items():
        data = {}
        for name in people:
            if name != rater_name:
                data[f"score_{site.player(group, name).id}"] = "4" if name == "keeper2" else "3"
        rater.post("/ratings", data=data)
    for person in people.values():
        person.post("/attendance", data={"status": "in"})
    admin.post("/teams")
    return admin, people


def test_members_see_team_scores_but_not_individual_ratings(site):
    admin, people = rated_game(site)
    page = people["alice"].get("/").text
    assert "Why these teams" in page and "Team score" in page
    assert "Individual ratings" not in page
    assert "How the split was scored" in page
    # Position ratings plus a team score could reveal one person's rating.
    table = page.split('class="compare"')[1].split("</table>")[0]
    assert "rated " not in table


def test_admins_see_individual_ratings_on_the_team_screen(site):
    admin, _ = rated_game(site)
    page = admin.get("/").text
    assert "Individual ratings" in page and "Only group admins can see these." in page
    keepers = page.split("Goalkeepers</th>")[1].split("</tr>")[0]
    assert "rated" in keepers
