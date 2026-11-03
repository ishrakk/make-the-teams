# Database

PostgreSQL tables, defined with SQLAlchemy.

| File | Purpose |
| --- | --- |
| [`models.py`](models.py) | The tables and their constraints. |
| [`session.py`](session.py) | Connection setup. |

## Tables

```mermaid
erDiagram
    players ||--o{ rsvps : answers
    games ||--o{ rsvps : has
    games ||--o| team_splits : has
    team_splits ||--|{ team_assignments : contains
    players ||--o{ team_assignments : "placed in"

    players {
        int id PK
        string name "unique, ignoring case"
        string primary_position
        string secondary_position "optional"
        bool active
    }
    games {
        int id PK
        date game_date "unique"
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
```

## Design choices

- **The database enforces the important rules.** Check constraints limit positions,
  statuses and teams to valid values, and an index on `lower(name)` makes names
  unique ignoring case. A bug in the app can't store bad data.
- **Each game keeps one split.** Making teams again replaces it. The stored `seed`
  and the players who were in are enough to reproduce a split with the same code
  and weights.
- **Removing a player hides them.** `active` turns false, so past games keep their
  names. Adding the same name again brings them back.
- **Positions are text with a check constraint**, not a PostgreSQL enum, because
  changing a check constraint in a migration is simpler.

## Changing a table

Edit `models.py`, then add a migration as described in
[`migrations/README.md`](../../migrations/README.md).
