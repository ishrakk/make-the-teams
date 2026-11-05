# Metrics

What the site reports to Prometheus, in [`collector.py`](collector.py). Set `METRICS_PORT` to
serve them. They use their own port, so the public site never exposes them.

| What you want to know | Metric | Source |
| --- | --- | --- |
| Service uptime | `process_start_time_seconds`, `up` | App, Prometheus |
| Recently active users | `teams_active_users{window="15m" or "24h" or "7d"}` | Database |
| Total users | `teams_users` | Database |
| Groups and players | `teams_groups`, `teams_players_approved` | Database |
| Database size | `teams_database_size_bytes` | Database |
| Requests and errors | `teams_http_requests_total{method, route, status}` | App |
| Response time | `teams_http_request_duration_seconds` | App |
| CPU, memory and disk | `node_*` | Node exporter |

## Why active users, not active sessions

Sessions are signed cookies stored in the browser, so the server doesn't have a list to
count. A session also stays valid for 90 days, so counting them would say little about real
use. Instead, `users.last_seen_at` is updated at most every 5 minutes, and the 15-minute window
is the closest measure of who's using the site now.

## Design notes

- **Totals come from the database when Prometheus asks,** cached for 30 seconds. With two web
  pods, each reports the same totals, so the dashboard uses `max()`.
- **Requests are labeled by route pattern,** such as `/join/{code}`, never the real URL. Real
  URLs contain group codes and reset tokens, and would create endless time series.
- **A database failure doesn't break metrics.** Process metrics continue, and the totals show
  as a gap.
- **Only totals are reported.** No metric names a person or a group.

`last_seen_at` is personal data: it's removed with the account, and should be mentioned in
the site's privacy note.
