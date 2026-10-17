# Scheduling (macOS launchd)

Runs the LinkedIn agents unattended so Agent Inbox only shows new, still-unhandled items.

| Agent | Schedule | What it does |
|---|---|---|
| `com.personal-linkedin-agent.daily-run` | Daily 06:30 | `daily_run.py --headless`: recover interrupted reviews, close items handled on LinkedIn, propose new items, and post a summary |
| `com.personal-linkedin-agent.langgraph-server` | At login, kept alive | `langgraph dev --no-reload`, which holds review history and performs explicit Agent Inbox actions immediately |

launchd runs missed calendar jobs when the Mac wakes.

The retired `apply-run` job is no longer installed. `uninstall.sh` still removes an older installed copy.

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
