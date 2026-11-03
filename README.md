# Make the Teams

Replaces a weekly WhatsApp poll for Saturday pickup soccer. Players say whether
they're in, and the site splits them into two teams balanced by position.

<img src="docs/teams.png" alt="Two teams of players laid out on a soccer pitch" width="360">

## How it fits together

```mermaid
flowchart LR
    phone[Phone browser] --> web[web: pages and sign-in]
    web --> games[games: rules]
    games --> splitter[splitter: team logic]
    games --> db[db: tables]
    db --> pg[(PostgreSQL)]
```

| Module | What it does | Read more |
| --- | --- | --- |
| `app/splitter` | Splits players into teams. Standard library only. | [README](app/splitter/README.md) |
| `app/games` | Rules for players, games, RSVPs and teams. | [README](app/games/README.md) |
| `app/web` | Pages, sign-in and health checks. | [README](app/web/README.md) |
| `app/db` | Database tables. | [README](app/db/README.md) |
| `migrations` | Database schema changes. | [README](migrations/README.md) |
| `deploy` | Kubernetes manifests. | [README](deploy/README.md) |
| `tests` | The test suite. | [README](tests/README.md) |

**To review how teams are made, start with the
[splitter README](app/splitter/README.md).**

## Run it

```bash
docker compose up --build
```

Open http://localhost:8000 and sign in with `organiser` to make teams, or `friends`
as a regular player.

## Try the team logic on its own

No database or web server needed:

```bash
python -m app.splitter app/splitter/examples/roster.csv --seed 7
```

## Develop

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
docker compose up -d db
```

Then set the environment for the commands below. `SECURE_COOKIES=false` is needed
for local `http://`.

```bash
export DATABASE_URL=postgresql+psycopg://teams:teams@localhost/teams
export SESSION_SECRET=local-development-only-not-a-real-secret
export GROUP_PASSCODE=friends ADMIN_PASSCODE=organiser SECURE_COOKIES=false

alembic upgrade head
uvicorn --factory app.web.main:create_app --reload
```

See [tests/README.md](tests/README.md) for running the tests.

## Technology

| Choice | Why |
| --- | --- |
| FastAPI with server-rendered pages | Forms and links are enough. No front-end build to maintain. |
| PostgreSQL with SQLAlchemy and Alembic | The data is relational, and constraints protect it. |
| Kubernetes with Kustomize | Plain manifests, with no templating to learn. |
| GitHub Actions | Tests each pull request and publishes an image from `main`. |

## Next

- Peer ratings, so skill is balanced as well as position
- Database backups
- A cluster to run it on
