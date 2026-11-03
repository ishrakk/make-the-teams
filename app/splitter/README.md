# Team splitter

Takes the players who said they're in and returns two teams balanced by position and
skill, a position for each player, a score that explains the result, and warnings for
the group's admins.

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
  GK  Adam
  DEF Eli
  DEF Gabe
  MID Hassan
  MID Jamal
  FWD Liam
  FWD Marco

Team B (7)
  GK  Bilal
  DEF Dev
  DEF Farid
  MID Carlos  (secondary)
  MID Ivan
  FWD Kofi
  FWD Nabil

Cost
  missing_keeper          0.00
  extra_keeper            0.00
  position_imbalance      0.00
  shape                   0.48
  off_position            2.00
  skill_gap               0.00
  total                   2.48
```

Each player lists a primary position and, optionally, a secondary one. They are
only ever given one of those two. They may also have a peer rating from 1 to 5.

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
| `skill_gap` | 2 | 2 × (rating advantage)² | Teams should be evenly matched. |

The ideal in `shape` comes from a 4-3-3: 40% of a team's outfield players in
defense, 30% in midfield and 30% up front.

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

### How skill balancing works

A player's rating is their average peer score, used once at least 3 people have rated
them. [`app/ratings`](../ratings/README.md) decides that.

Each rating is compared with the average of the rated players in the game, and those
differences are added up per team. The **rating advantage** is Team A's total minus Team
B's. Comparing with the average means:

- **Unrated players count as average**, so they don't pull a team either way.
- **A team one player short isn't penalized** for having a lower total.

With one player unrated, the example in [`roster_rated.csv`](examples/roster_rated.csv) gives
these teams, with `skill_gap` on and off:

| Setting | Team A average | Team B average | Gap |
| --- | --- | --- | --- |
| `skill_gap=2` (default) | 3.48 | 3.44 | 0.04 |
| `skill_gap=0` | 3.28 | 3.61 | 0.33 |

A gap of 1 point costs 2, about one player out of position. A gap of 2 points costs 8,
more than one uneven position at 5. So a large skill gap can make the split accept a
position imbalance, but keepers still come first, at 100 per team.

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

It makes 150 attempts. Half start with everyone on their
primary position and half start with about half the eligible players on their
secondary, because each kind gets stuck on rosters the other handles. Then it keeps
every result within 1.0 of the best cost and picks one at random.

Why not a formula for positions? Because hill climbing doesn't care what's in the
cost function, so you can add a new term without rewriting the search.

**Reshuffle:** ratings make exact ties rare, so always taking the very best split would
give the same teams every time. A tolerance of 1.0 is too small for anyone to notice (it
equals a rating gap of about 0.7 points), but it leaves plenty of different splits to
choose from. On the rated example, seeds 7 and 8 give different teams, costing 2.62 and
2.52. The same players and seed always give the same teams, so any result can be
reproduced from its seed. Set `TOLERANCE` in `search.py` to change this.

### How good is the search?

Output of `python -m app.splitter.benchmark`, run with no tolerance. With nobody rated,
it compares the search with the exact best cost on random rosters:

```text
players  with 2nd  rosters missed best  worst gap   slowest
     14       50%       30           0       0.00     0.14s
     14      100%       30           0       0.00     0.13s
     18       50%       30           0       0.00     0.22s
     18      100%       30           0       0.00     0.20s
     22       50%       30           0       0.00     0.27s
     22      100%       30           0       0.00     0.27s
     26       50%       30           0       0.00     0.35s
     26      100%       30           0       0.00     0.38s
     30       50%       30           2       2.00     0.49s
     30      100%       30           3       2.00     0.51s
```

Ratings rule out calculating the exact best on large rosters, so it compares 150 attempts
with 3,000 on the same rosters. `worst rating gap` is the largest gap between the teams'
average ratings:

```text
players  rosters   avg gap  worst gap  worst rating gap
     14        8     0.000      0.000             0.014
     18        8     0.000      0.000             0.011
     22        8     0.000      0.000             0.009
     26        8     0.000      0.000             0.008
```

Without ratings, it missed the best cost on 0 of 240 rosters up to 26 players. At 30 players it missed on 5 of 60, by at most 2.0, the cost of one extra player out of position.

If that matters, raise `RESTARTS` in `search.py`; time grows in proportion. The tests also
compare the search with a brute-force check of every possible split on small rosters,
with and without ratings.

## Decisions for you to review

These are the choices most likely to need your input. The defaults are guesses
until they've met your real group.

1. **How much should skill matter against position?** `skill_gap=2` is my starting guess.
   Try your real group's ratings with `--weight skill_gap=N`. Higher values accept more
   position imbalance for closer skill.
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
   A term that penalizes repeating past pairings would fix that, using stored
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
4. Add a test to `tests/test_splitter.py` for the behavior you want.
5. Run `pytest tests/test_splitter.py` and `python -m app.splitter.benchmark`.

A roster CSV has the columns `name,primary,secondary,rating`. The last two can be blank.
If a new term depends on individual players, `optimal_cost()` in `benchmark.py` no longer
applies, so rely on the brute-force check in the tests.
