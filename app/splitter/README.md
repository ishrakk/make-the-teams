# Team splitter

Takes the players who said they're in and returns two teams, a position for
each player, a score that explains the result, and warnings for the organiser.

It uses only the Python standard library, so you can run and tune it without a
database or web server.

| File | Purpose |
| --- | --- |
| [`cost.py`](cost.py) | **What a good split means.** Weights and scoring. Most changes go here. |
| [`search.py`](search.py) | How the lowest-cost split is found. |
| [`models.py`](models.py) | `Player`, `Assignment` and `SplitResult`. |
| [`__main__.py`](__main__.py) | Command line tool for trying rosters and weights. |
| [`benchmark.py`](benchmark.py) | Compares the search with the true best cost. |

## Try it

```bash
python -m app.splitter app/splitter/examples/roster.csv --seed 7
```

```text
seed 7

Team A (7)
  GK  Bilal
  DEF Dev
  DEF Gabe
  MID Farid  (secondary)
  MID Hassan
  FWD Kofi
  FWD Marco

Team B (7)
  GK  Adam
  DEF Carlos
  DEF Eli
  MID Ivan
  MID Jamal
  FWD Liam
  FWD Nabil

Cost
  missing_keeper          0.00
  extra_keeper            0.00
  position_imbalance      0.00
  shape                   0.48
  off_position            2.00
  total                   2.48
```

Each player lists a primary position and, optionally, a secondary one. They are
only ever given one of those two.

## The rules

**One hard rule:** team sizes differ by at most one. With an odd number of
players, Team A has the extra player.

**Everything else is a preference**, scored by a cost function. Lower is better.

| Term | Weight | Calculation | Why |
| --- | --- | --- | --- |
| `missing_keeper` | 100 | 100 per team with no keeper | Each team needs someone in goal. |
| `extra_keeper` | 20 | 20 per keeper beyond the first on a team | A second keeper is wasted in goal. |
| `position_imbalance` | 5 | 5 × (A − B)², for DEF, MID and FWD | Teams should match position for position. |
| `shape` | 1 | (actual − ideal)², per team and position | Each team should resemble a real formation. |
| `off_position` | 2 | 2 per player on their secondary | People prefer their own position. |

The ideal in `shape` comes from a 4-3-3: 40% of a team's outfield players in
defence, 30% in midfield and 30% up front.

### Reading the example

The roster has 2 GK, 5 DEF, 3 MID and 4 FWD.

- **Keepers:** one per team, so both keeper terms are 0.
- **Why Farid moved:** with 5 DEF and 3 MID, both positions split unevenly at
  best, costing 5 × 1² + 5 × 1² = 10 in `position_imbalance`. Moving one defender
  to midfield makes 4 DEF and 4 MID, which removes that cost for only 2 in
  `off_position`.
- **Shape:** each team has 6 outfield players, so the ideal is 2.4 / 1.8 / 1.8.
  The actual 2 / 2 / 2 costs 0.4² + 0.2² + 0.2² = 0.24 per team, or 0.48 in total.

Only a DEF → MID move fixes both positions, and Carlos and Farid are the two
defenders who list MID as a secondary. The choice between them comes down to the
random start. The splitter has no idea who minds moving more.

### What the warnings look like

When no split can avoid a problem, the search still returns its best result and
says what's wrong. With one keeper and 11 players:

```text
Warnings
  Odd number of players (11): Team B is one player short.
  Team B has no keeper. They will need to rotate.
```

Nobody is put in goal unless they listed GK as a position.

## How the search works

Each attempt shuffles players into two even teams, then makes improvements until
none is left:

1. Try swapping two players between teams.
2. Try moving a player between primary and secondary.
3. Keep any change that lowers the cost.

It makes 150 attempts and keeps the best. Half start with everyone on their
primary position and half start with about half the eligible players on their
secondary, because each kind gets stuck on rosters the other handles.

Why not a formula for positions? Because hill climbing doesn't care what's in the
cost function, so you can add a new term without rewriting the search.

**Reshuffle:** many splits tie for best, and random starts land on different
ones. Seed 8 gives different teams at the same cost of 2.48. The same players and
seed always give the same teams, so any result can be reproduced from its seed.

### How good is the search?

Output of `python -m app.splitter.benchmark`, which compares it with the exact
best cost on random rosters:

```text
players  with 2nd  rosters missed best  worst gap   slowest
     14       50%       30           0       0.00     0.10s
     14      100%       30           0       0.00     0.13s
     18       50%       30           0       0.00     0.19s
     18      100%       30           0       0.00     0.22s
     22       50%       30           0       0.00     0.32s
     22      100%       30           0       0.00     0.28s
     26       50%       30           0       0.00     0.34s
     26      100%       30           0       0.00     0.37s
     30       50%       30           2       2.00     0.46s
     30      100%       30           3       2.00     0.52s
```

It found the best cost on all 240 rosters up to 26 players. At 30 players it
missed on 5 of 60, each time by 2.0, the cost of one extra player out of position.
If that matters, raise `RESTARTS` in `search.py`; time grows in proportion.

## Decisions for you to review

These are the choices most likely to need your input. The defaults are guesses
until they've met your real group.

1. **Skill is ignored, and this is the biggest gap.** Your three best players can
   land on the same team if the positions work out. Reshuffle is the only remedy
   until peer ratings exist.
2. **Is 4-3-3 right for your games?** It's set by `Weights.formation`. A share
   that doesn't suit your numbers just adds `shape` cost, and pulls players off
   position if it's strong enough.
3. **How willing are people to move?** At `off_position=2`, a player moves whenever
   that evens out two positions. To keep everyone on primary in the example, it
   takes a weight above 10.8: at `off_position=12`, one team gets 3 DEF and 1 MID and
   the cost is 11.28.
4. **Should someone be forced into goal?** Today, no: the team rotates and gets a
   warning. Change that by treating GK as everyone's fallback.
5. **Who moves is random.** A per-player "happy to move" flag or the
   number of recent games off position could break those ties.
6. **Last week isn't considered.** You could get the same teams two weeks running.
   A term that penalises repeating past pairings would fix that, using stored
   splits.
7. **Friends and carpools aren't considered.** Nor are late arrivals or who brought
   bibs. Add terms only if these turn out to matter.

## How to change it

1. Try a weight without editing code:
   ```bash
   python -m app.splitter roster.csv --seed 7 --weight off_position=12
   ```
2. Make it permanent in `Weights` in `cost.py`.
3. To add a rule, add a weight, a field on `CostBreakdown`, and the calculation in
   `score()`. Add the term to `total` and to `COST_TERMS` in `__main__.py`.
4. Add a test to `tests/test_splitter.py` for the behaviour you want.
5. Run `pytest tests/test_splitter.py` and `python -m app.splitter.benchmark`.

### Adding peer ratings later

1. Add `rating: float | None` to `Player`.
2. Have `_State` keep each team's rating total, updating it in `swap()`.
3. Pass the totals to `score()` and add a term such as
   `rating_gap × (total A − total B)²`.

The search stays the same, and ratings can then be blended with position balance
by weight. `optimal_cost()` in `benchmark.py` stops being valid, because players in
the same position would no longer be interchangeable. Test against the small
brute-force check in `tests/test_splitter.py` instead, after adding ratings to it.
