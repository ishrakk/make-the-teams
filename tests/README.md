# Tests

```bash
pytest tests/test_splitter.py   # no database needed

export TEST_DATABASE_URL=postgresql+psycopg://teams:teams@localhost/teams_test
pytest                          # everything
```

Without `TEST_DATABASE_URL`, database tests are skipped. **The test database is wiped**,
so its name must contain `test`.

| File | What it covers |
| --- | --- |
| [`test_splitter.py`](test_splitter.py) | Team rules, warnings and repeatability. Also compares the search with a brute-force check of every possible split on small rosters. |
| [`test_games.py`](test_games.py) | Player, RSVP and team rules, including constraints enforced by the database. |
| [`test_web.py`](test_web.py) | Sign-in, permissions, a full journey from RSVP to teams, and escaping of user input. |
| [`conftest.py`](conftest.py) | Shared setup. |

Database tests run on real PostgreSQL with the real migrations, not SQLite, because
the app relies on PostgreSQL features such as `ON CONFLICT` and row locks.
Migrations are therefore tested on every run too.

CI runs all of this, plus `ruff`, on every pull request. See
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
