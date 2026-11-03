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
| [`test_splitter.py`](test_splitter.py) | Team rules, skill balancing, warnings and repeatability. Also compares the search with a brute-force check of every possible split on small rosters. |
| [`test_accounts.py`](test_accounts.py) | Sign-up, sign-in, password storage, resets, attempt limits and deleting an account. |
| [`test_groups.py`](test_groups.py) | The journey from sign-up to teams, approval, admin permissions, and keeping groups separate. |
| [`test_ratings.py`](test_ratings.py) | Anonymity, who can rate whom, and who can see averages. |
| [`test_games.py`](test_games.py) | Attendance, teams, and ratings reaching the splitter. |
| [`conftest.py`](conftest.py) | Shared setup, including a separate browser for each person. |

Database tests run on real PostgreSQL with the real migrations, not SQLite, because
the app relies on PostgreSQL features such as `ON CONFLICT` and row locks.
Migrations are therefore tested on every run too.

CI runs all of this, plus `ruff`, on every pull request. See
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml).
