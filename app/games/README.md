# Games

The rules for players, games, RSVPs and teams, in [`service.py`](service.py). The
website calls these functions, and they connect the database to the
[splitter](../splitter/README.md).

| Function | What it does |
| --- | --- |
| `add_player`, `update_player`, `remove_player` | Manage the player list. Names are tidied and must be unique. |
| `next_game_date` | The next game day, which is today if today is a game day. |
| `get_or_create_game` | Creates each week's game the first time anyone needs it. |
| `set_rsvp` | Records in or out. A new answer replaces the old one. |
| `make_teams` | Runs the splitter on the players who are in and stores the result. |
| `game_view` | Everything the game page shows. |

## Behaviour worth knowing

- **The current game moves on by itself.** There's no scheduler. The site shows the
  next Saturday, and from Sunday that's the following week, with a fresh set of
  answers.
- **Teams can go out of date.** If someone changes their answer after teams are made,
  the teams stay as they were and the page says the list has changed. An organiser
  decides whether to make them again, since reshuffling everyone over one late
  change may not be wanted.
- **Two organisers can press the button together.** `make_teams` locks the game's
  row, so the second waits and its result replaces the first.
- **Errors for users are `GameError`.** The message is written to be shown as it is.
  Anything else is a bug and should surface as one.
