# Scheduling (macOS launchd)

Runs the LinkedIn agents unattended so Agent Inbox only shows new, still-unhandled items.

| Agent | Schedule | What it does |
|---|---|---|
| `com.personal-linkedin-agent.daily-run` | Daily 06:30 | `daily_run.py --mode full --headless`: apply decisions, close stale items, propose new items, post a summary notification |
| `com.personal-linkedin-agent.apply-run` | Every 2 hours, 07:00-21:00 | `daily_run.py --mode apply --headless`: apply and cleanup only (no LLM calls) |
| `com.personal-linkedin-agent.langgraph-server` | At login, kept alive | `langgraph dev`, which holds review history and dedup state |

launchd runs missed calendar jobs when the Mac wakes.

## Install

```shell
# one-time: log in with a visible browser so playwright/.auth/state.json exists
uv run python invitations_manager.py --num-to-process 1
./scheduling/install.sh
```

To change the cadence, edit the `StartCalendarInterval` in the plist templates and re-run `install.sh`.
Logs: `logs/daily_run.log` (plus launchd stdout/stderr in `logs/`).

## Uninstall

```shell
./scheduling/uninstall.sh
```

## Exit codes

`0` success; `1` health failure (a scrape returned nothing, so nothing was closed); `2` LinkedIn login needed (a macOS notification is posted).
