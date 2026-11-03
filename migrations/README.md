# Migrations

Database schema changes, managed by [Alembic](https://alembic.sqlalchemy.org/).
Each file in `versions/` is one change.

Everything here needs `DATABASE_URL` set, for example
`postgresql+psycopg://teams:teams@localhost/teams`.

```bash
alembic upgrade head                              # apply all migrations
alembic revision --autogenerate -m "add ratings"  # generate one from models.py
alembic check                                     # do models.py and the database match?
alembic downgrade -1                              # undo the latest migration
```

Always read a generated migration before committing it. Autogenerate misses some
changes, including edits to check constraints.

## Running in production

In Kubernetes, every web pod runs `alembic upgrade head` in an init container
before it starts. Pods often start together, so [`env.py`](env.py) takes a PostgreSQL
advisory lock: one pod migrates while the others wait, then they find nothing to do.

During a rolling update, old pods keep running against the new schema for a short
time. Make changes in a form the old code tolerates. To rename a column, for
example, add the new one in one release and drop the old one in a later release.
