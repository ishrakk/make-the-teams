# Test users

Lets you try the site as many different people without anyone signing up. It only runs
when `DEMO_MODE=true`.

`docker compose up` turns this on and creates the test users for you. Without Docker:

```bash
export DEMO_MODE=true SECURE_COOKIES=false
python -m app.demo          # Create the test users. Safe to run again.
python -m app.demo --reset  # Delete them and start over.
```

Then open `/demo` and tap a person to become them. A bar at the top of every page shows
who you are and links back. Everyone also has the email `<name>@example.test` and the
password `demo-password`.

## What's created

| Who | Shows you |
| --- | --- |
| Adam | An admin of Saturday Crew and a member of Thursday Night |
| Bilal | An admin of Thursday Night and a member of Saturday Crew |
| Liam | A member who hasn't voted this week |
| Gabe, Marco | Members who voted out |
| Omar | A request waiting for an admin's approval |
| Everyone else | Members who voted in |

Saturday Crew has 14 players who have all rated each other, so admins can see averages
and teams balance on skill right away. Test votes are only for the current week, so use
`--reset` to fill in a new week.

## Why this can't reach a real deployment

- **The site won't start** with `DEMO_MODE=true` unless `SECURE_COOKIES=false`, and
  production uses secure cookies.
- **Without demo mode, `/demo` doesn't exist**, and `python -m app.demo` refuses to run.
- **Switching only reaches test accounts.** Real accounts return "not found", even in demo
  mode. Only `@example.test` emails count, a domain reserved for testing.
- **`--reset` deletes only test data:** the two test groups and `@example.test` accounts.

Anyone who can reach a site in demo mode can sign in as any test user, so don't expose it
to the internet.
