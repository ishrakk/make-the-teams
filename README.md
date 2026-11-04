# Make the Teams

Replaces the weekly WhatsApp poll for pickup soccer. Anyone can create a group and invite
friends. An admin approves each player, players vote on whether they're coming and
rate each other anonymously, and the site splits them into two teams balanced by
position and skill.

<img src="docs/teams.png" alt="Two teams of players laid out on a soccer pitch" width="360">

## How it fits together

```mermaid
flowchart LR
    phone[Phone browser] --> web[web: pages]
    web --> accounts[accounts]
    web --> groups[groups: joining and admins]
    web --> games[games: attendance and teams]
    web --> ratings[ratings: anonymous scores]
    games --> ratings
    games --> splitter[splitter: team logic]
    accounts --> pg[(PostgreSQL)]
    groups --> pg
    games --> pg
    ratings --> pg
```

| Module | What it does | Read more |
| --- | --- | --- |
| `app/splitter` | Splits players into teams. Standard library only. | [README](app/splitter/README.md) |
| `app/ratings` | Anonymous 1 to 5 peer ratings. | [README](app/ratings/README.md) |
| `app/groups` | Creating and joining groups, and admin approval. | [README](app/groups/README.md) |
| `app/accounts` | Email and password accounts. | [README](app/accounts/README.md) |
| `app/games` | Attendance and teams. | [README](app/games/README.md) |
| `app/web` | Pages and sessions. | [README](app/web/README.md) |
| `app/db` | Database tables. | [README](app/db/README.md) |
| `migrations` | Database schema changes. | [README](migrations/README.md) |
| `deploy` | Kubernetes manifests. | [README](deploy/README.md) |
| `app/demo` | Test users for trying the site locally. | [README](app/demo/README.md) |
| `tests` | The test suite. | [README](tests/README.md) |

**To review how teams are made, start with the
[splitter README](app/splitter/README.md).**

## Run it

```bash
docker compose up --build
```

Open http://localhost:8000/demo and tap a test user to see the site as them. No sign-up is
needed, and you can switch at any time. See [app/demo/README.md](app/demo/README.md).

To reach the site from another machine, set its address so that invite links work:

```bash
PUBLIC_URL=http://<this machine's IP>:8000 docker compose up
```

Password reset emails go to the log. `docker-compose.yml` is for local testing only: it turns
on test users and uses fixed secrets, so don't use it to run the real site.

## Try the team logic on its own

No database or web server needed:

```bash
python -m app.splitter app/splitter/examples/roster_rated.csv --seed 7
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
export RATING_SECRET=local-development-only-not-a-real-secret
export PUBLIC_URL=http://localhost:8000 SECURE_COOKIES=false LOG_EMAILS=true DEMO_MODE=true

alembic upgrade head
python -m app.demo
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

- Email for password resets, then verified sign-ups and join-request notifications
- Database backups
- A cluster to run it on
