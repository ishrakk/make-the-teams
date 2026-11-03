# Website

Server-rendered pages using FastAPI and Jinja templates. There's no JavaScript and
no build step, and pages are designed for a phone first, since links arrive through
WhatsApp.

| File | Purpose |
| --- | --- |
| [`main.py`](main.py) | Builds the app: settings, sessions and static files. |
| [`routes.py`](routes.py) | Pages, form handlers and health checks. No rules live here. |
| [`auth.py`](auth.py) | Passcode sign-in. |
| [`templates/`](templates) | HTML pages. |
| [`static/`](static) | Styles and the self-hosted Barlow font. |

## Routes

| Route | Who | What it does |
| --- | --- | --- |
| `GET /login`, `POST /login` | Anyone | Sign in with a passcode. |
| `POST /logout` | Anyone | Sign out. |
| `GET /` | Member | This week's game. |
| `POST /rsvp` | Member | Answer in or out. |
| `POST /teams` | Organiser | Make or reshuffle teams. |
| `GET /players`, `POST /players` | Member | See and add players. |
| `GET /players/{id}`, `POST /players/{id}` | Member | Edit a player. |
| `POST /players/{id}/remove` | Organiser | Remove a player. |
| `GET /healthz` | Anyone | The process is running. Kubernetes liveness probe. |
| `GET /readyz` | Anyone | The database is reachable. Kubernetes readiness probe. |

## Sign-in

There are no accounts. Everyone shares a group passcode and organisers share a second
one, so nobody has to register to answer a poll. A signed cookie remembers the
role for 90 days.

Known limits, which are reasonable for a group of friends but worth revisiting
before opening this up further:

- Anyone with the group passcode can answer for anyone else, like a shared poll. This
  also lets an organiser answer for someone who isn't on their phone.
- There's no limit on sign-in attempts. Use a long passcode, or add rate limiting at
  the ingress.
- Changing a passcode doesn't sign out existing sessions. Changing `SESSION_SECRET`
  signs out everyone.

Forms are protected from other websites by the `SameSite=Lax` session cookie.

## Settings

Set through environment variables, defined in [`app/config.py`](../config.py).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Required | `postgresql+psycopg://user:password@host/db` |
| `SESSION_SECRET` | Required | At least 32 characters. Signs the session cookie. |
| `GROUP_PASSCODE` | Required | For everyone. |
| `ADMIN_PASSCODE` | Required | For organisers. |
| `GAME_WEEKDAY` | `5` | Game day. Monday is 0 and Saturday is 5. |
| `TIMEZONE` | `America/New_York` | Decides when "today" changes. |
| `SECURE_COOKIES` | `true` | Set to `false` only for local `http://`. |
