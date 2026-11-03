# Database

PostgreSQL tables, defined with SQLAlchemy.

| File | Purpose |
| --- | --- |
| [`models.py`](models.py) | The tables and their constraints. |
| [`session.py`](session.py) | Connection setup. |

## Tables

```mermaid
erDiagram
    users ||--o{ players : "plays as"
    users ||--o{ password_resets : requests
    groups ||--o{ players : has
    groups ||--o{ games : has
    players ||--o{ rsvps : answers
    games ||--o{ rsvps : has
    games ||--o| team_splits : has
    team_splits ||--|{ team_assignments : contains
    players ||--o{ team_assignments : "placed in"
    players ||--o{ ratings : receives

    users {
        int id PK
        string email "unique, lowercase"
        string password_hash "Argon2id"
        int session_epoch
    }
    password_resets {
        string token_hash PK
        int user_id FK
        timestamp expires_at
    }
    groups {
        int id PK
        string name
        string join_code "unique"
        int game_weekday
        string timezone
    }
    players {
        int id PK
        int group_id FK
        int user_id FK
        string name "unique in group, ignoring case"
        string primary_position
        string secondary_position "optional"
        string role "member or admin"
        string status "pending, approved or removed"
    }
    games {
        int id PK
        int group_id FK
        date game_date "unique in group"
    }
    rsvps {
        int game_id PK
        int player_id PK
        string status "in or out"
    }
    team_splits {
        int game_id PK
        bigint seed
        float cost_total
        json warnings
    }
    team_assignments {
        int game_id PK
        int player_id PK
        string team "A or B"
        string position
    }
    ratings {
        int rated_player_id PK
        string rater_tag PK "keyed hash, not the rater"
        int score "1 to 5"
    }
```

`rate_limits` stands apart. See [`app/ratelimit.py`](../ratelimit.py).

## Design choices

- **The database enforces the important rules.** Check constraints limit positions,
  statuses, roles and scores to valid values. A bug in the app can't store bad data.
- **`players` connects an account to a group**, along with that person's name, positions,
  role and approval status there.
- **Removing a player keeps their row**, with `status = 'removed'`, so past games keep
  their names. Their name becomes free, through a partial unique index, and their ratings
  are deleted. Deleting an account removes everything, including from past teams.
- **`ratings` has no rater column or timestamp.** See
  [`app/ratings/README.md`](../ratings/README.md).
- **Each game keeps one split.** Making teams again replaces it.

## Changing a table

Edit `models.py`, then add a migration as described in
[`migrations/README.md`](../../migrations/README.md).
