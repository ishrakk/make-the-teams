# Accounts

Email and password accounts. One account can be in many groups.

| File | Purpose |
| --- | --- |
| [`service.py`](service.py) | Signing up, checking passwords, and password resets. |
| [`email.py`](email.py) | Sends the password reset email over SMTP. |

## How passwords are protected

- **Hashing:** passwords are stored only as Argon2id hashes, using the `argon2-cffi`
  defaults, with at least 10 and at most 128 characters.
- **Memory limit:** each hash uses 64 MiB by design, so at most 4 run at once in a pod.
  Otherwise a burst of sign-ins could run it out of memory.
- **Changing a password** signs out every other device, through `users.session_epoch`.

## Password resets

A reset link holds a random token, valid once for an hour. Only its SHA-256 hash is
stored, so reading the database doesn't give anyone a working link. A fast hash is safe
here because the token is long and random, unlike a password.

Resets need SMTP settings. Without them the site hides the "Forgot your password?" link,
and says so on the reset page. For local development, `LOG_EMAILS=true` writes the email
to the log instead. Never set that in production, because it would put working reset
links in the logs.

## What's limited

| What | Limit |
| --- | --- |
| Wrong passwords per visitor | 30 in 15 minutes |
| Wrong passwords per email | 10 in 15 minutes |
| New accounts per visitor | 10 a day |
| Reset emails per visitor | 10 an hour |
| Reset emails per address | 3 an hour |

The limits are defined in [`app/ratelimit.py`](../ratelimit.py). They're stored in
PostgreSQL so all web pods share them. Visitor addresses and emails are stored in them
only as keyed hashes.

## Known gaps

- **Email addresses aren't verified at sign-up.** Someone could sign up with an address
  they don't own. The real owner can take the account back with a password reset, which
  also signs the other person out. Verification would need email to be set up first.
- **Sign-up reveals whether an email has an account**, because it says so. Hiding that
  would need verification emails too. Login and password reset don't reveal it.
- **The per-email limit can lock someone out for 15 minutes** if another person keeps
  guessing their password.
- **There's no two-factor authentication.**
