# Website

Server-rendered pages using FastAPI and Jinja templates, designed for a phone first. The
only JavaScript fills in your time zone when you create a group.

## Color themes

`SITE_THEME` chooses `midnight`, `graphite`, `petrol` or `oxblood`. Each is a short block of
colors at the top of [`static/style.css`](static/style.css). To change a color or add a
theme, edit that block and the list in [`app/config.py`](../config.py).

| File | Purpose |
| --- | --- |
| [`main.py`](main.py) | Builds the app: settings, sessions, headers and static files. |
| [`routes.py`](routes.py) | Pages, form handlers and health checks. No rules live here. |
| [`auth.py`](auth.py) | Works out who the visitor is and which group they're viewing. |
| [`demo_routes.py`](demo_routes.py) | Test user switching. Only added in demo mode. |
| [`templates/`](templates) | HTML pages. |
| [`static/`](static) | Styles and the self-hosted Barlow font. |

## Routes

| Route | Who | What it does |
| --- | --- | --- |
| `GET /` | Anyone | The home page, or this week's game once you're in a group. |
| `/signup`, `/login`, `POST /logout` | Anyone | Accounts. |
| `/forgot`, `/reset/{token}` | Anyone | Password reset. |
| `/account`, `POST /account/password`, `POST /account/delete` | Signed in | Manage your account. |
| `GET /groups`, `POST /groups/{id}/open` | Signed in | Your groups, shown after logging in, and opening one. |
| `GET /groups/new`, `POST /groups` | Signed in | Create a group. |
| `/join`, `/join/{code}` | Anyone, signed in to ask | Enter a code and ask to join. |
| `POST /attendance` | Member | Vote in or out for this week. |
| `GET /ratings`, `POST /ratings` | Member | Rate other players. |
| `GET /group`, `POST /group/profile`, `POST /group/leave` | Member | Invite link, players, your details. |
| `POST /teams` | Admin | Make or reshuffle teams. |
| `POST /group/requests/{id}/approve`, `.../decline` | Admin | Answer join requests. |
| `POST /group/players/{id}/role`, `.../remove` | Admin | Manage players. |
| `POST /group/settings`, `/group/code`, `/group/delete` | Admin | Manage the group. |
| `GET /demo`, `POST /demo/switch/{id}` | Demo mode only | Switch between test users. |
| `GET /healthz` | Anyone | The process is running. Kubernetes liveness probe. |
| `GET /readyz` | Anyone | The database is reachable. Kubernetes readiness probe. |

## Security notes

- **Group separation:** admin routes act only on the group you're viewing, and look up
  players within it, so an ID from another group counts as not found.
- **Sessions:** a signed cookie lasting 90 days holds your user ID. It's `HttpOnly`,
  `SameSite=Lax`, and HTTPS-only in production.
- **Forged forms:** `SameSite=Lax` stops other sites from submitting forms using your
  session.
- **Secret links:** `Referrer-Policy: no-referrer` keeps invite and reset links from
  reaching other sites, and only the home page can be indexed by search engines.

## Settings

Set through environment variables, defined in [`app/config.py`](../config.py).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Required | `postgresql+psycopg://user:password@host/db` |
| `SESSION_SECRET` | Required | At least 32 characters. Signs the session cookie. |
| `RATING_SECRET` | Required | At least 32 characters. Hides who gave each rating. |
| `PUBLIC_URL` | Required | The site's address, used in invite and reset links. |
| `SECURE_COOKIES` | `true` | Set to `false` only for local `http://`. |
| `TRUSTED_PROXY_HOPS` | `0` | Proxies in front of the app, for attempt limits. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM` | Off | Password reset email. |
| `LOG_EMAILS` | `false` | Local development only: log emails instead of sending them. |
| `SITE_THEME` | `midnight` | The color theme. |
| `DEMO_MODE` | `false` | Local testing only: test users. See [`app/demo`](../demo/README.md). |
