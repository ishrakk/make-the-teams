# Games

Games, attendance and teams, in [`service.py`](service.py). The website calls these
functions, and they connect the database to the [splitter](../splitter/README.md).

| Function | What it does |
| --- | --- |
| `next_game_date` | The next game day, which is today if today is a game day. |
| `current_game` | This group's next game, by the date in the group's time zone. |
| `set_attendance` | Records a player's in or out. A new answer replaces the old one. |
| `make_teams` | Runs the splitter on the players who are in and stores the result. |
| `game_view` | Everything the game page shows, including `roster`: every player in the group with their answer. |

## Behavior worth knowing

- **The current game moves on by itself.** There's no scheduler. The site shows the next
  game day, and the day after that it's the following week, with fresh answers.
- **People vote only for themselves.** An admin can't mark someone in, so everyone who
  plays needs an account.
- **Ratings feed the splitter here.** `make_teams` passes each player's average to the
  splitter, if at least 3 people have rated them. It only stores who's on each team, so
  the rating isn't exposed to anyone through the teams.
- **Teams can go out of date.** If someone changes their answer after teams are made, the
  teams stay as they were and the page says the list has changed. An admin decides
  whether to reshuffle, since it may not be worth changing everyone's team for one late
  change.
- **Two admins can press the button together.** `make_teams` locks the game's row, so the
  second waits and its result replaces the first.
