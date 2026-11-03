# Ratings

Each player can give every other player in their group one overall score from 1 to 5,
and change it at any time. The scores balance the teams through the
[splitter](../splitter/README.md).

## Who can see what

| Who | Can see |
| --- | --- |
| Anyone in the app, including admins | Never who gave a score |
| A player | Only the scores they gave |
| A group admin | Each player's average and how many people rated them, once at least 3 have |
| Other members | No averages, and nothing about their own rating |

## How the rater is hidden

The `ratings` table has only the player being rated, a tag and the score:

```text
rater_tag = HMAC-SHA256(RATING_SECRET, "rater_id:rated_id")
```

- **Updating works.** The app recalculates the tag to find a person's earlier score, so
  each person has one score per player.
- **Reading the database isn't enough.** Without the key, a tag can't be traced to a
  person. Each tag also covers one pair of players, so you can't tell that two scores
  came from the same person.
- **No timestamps.** The time a score was saved could be matched to server logs or to
  when someone was active. Web logs still record that someone saved ratings, but not
  what they gave or to whom.

### What this doesn't protect against

**This is confidential, not cryptographically anonymous.** Someone with both the
database and `RATING_SECRET`, such as the person running the site, could work out who
gave each score by recalculating tags. Storing the key separately from the database and
its backups keeps a leak of either one from being enough.

**Small numbers can give people away.** Hiding averages until 3 people have rated limits
this, but an admin who watches an average change right after asking one person to rate
could still make a good guess.

## Choices to review

- **`MIN_RATINGS = 3`** is the threshold for both showing an average to admins and using
  it for teams. Below that, the player counts as average.
- **Scores don't expire**, and a player's skill can change. Players can update their
  scores whenever they like, but nothing prompts them to.
- **Nothing corrects for harsh or generous raters**, or for tactical voting, such as
  someone rating everyone else low. Admins can only spot this in the averages.
- **Leaving a group deletes the scores** that player gave and received, so a person who
  rejoins starts over.
