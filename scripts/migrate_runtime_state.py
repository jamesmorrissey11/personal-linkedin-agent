"""Move runtime state out of a checkout into the per-user runtime folder (one-time, after #47).

Before #47, the LinkedIn login session, the LinkedIn lock, the LangGraph server's Agent Inbox data, and logs
were written inside the repo. They now live in `linkedin_agent.runtime.state_dir()`. Stop the LangGraph server
first, then run:

    uv run python scripts/migrate_runtime_state.py [--dry-run] [--checkout PATH]

Existing data in the runtime folder is never overwritten; a conflicting item is reported and left in place.
"""

import argparse
import shutil
import socket
import sys
from pathlib import Path

from linkedin_agent.runtime import browser_dir, langgraph_dir, logs_dir, state_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
SERVER_PORT = 2024


def planned_moves(checkout: Path) -> list[tuple[Path, Path]]:
    """(source, destination) pairs; directories are merged entry by entry."""
    artifacts = state_dir() / "artifacts"
    return [
        (checkout / "playwright" / ".auth" / "state.json", browser_dir() / "state.json"),
        (checkout / ".langgraph_api", langgraph_dir() / ".langgraph_api"),
        (checkout / "logs", logs_dir()),
        (checkout / ".superpowers", artifacts / "superpowers"),
        (checkout / ".playwright-mcp", artifacts / "playwright-mcp"),
    ]


def server_is_running(port: int = SERVER_PORT) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def move(source: Path, destination: Path, dry_run: bool) -> list[str]:
    """Move `source` to `destination`, merging directories; never overwrite. Returns report lines."""
    if not source.exists():
        return []
    if source.is_dir() and destination.is_dir():
        report = []
        for child in sorted(source.iterdir()):
            report += move(child, destination / child.name, dry_run)
        if not dry_run and not any(source.iterdir()):
            source.rmdir()
        return report
    if destination.exists():
        return [f"SKIPPED {source} (already exists at {destination})"]
    if not dry_run:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    return [f"{'would move' if dry_run else 'moved'} {source} -> {destination}"]


def remove_empty_legacy_dirs(checkout: Path, dry_run: bool) -> list[str]:
    report = []
    lock = checkout / "playwright" / ".auth" / "linkedin.lock"
    if lock.exists():
        report.append(f"{'would remove' if dry_run else 'removed'} stale lock {lock}")
        if not dry_run:
            lock.unlink()
    for directory in (checkout / "playwright" / ".auth", checkout / "playwright"):
        if directory.is_dir() and not any(directory.iterdir()):
            report.append(f"{'would remove' if dry_run else 'removed'} empty {directory}")
            if not dry_run:
                directory.rmdir()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--checkout", type=Path, default=REPO_ROOT, help="Checkout to migrate from (default: this repo).")
    parser.add_argument("--dry-run", action="store_true", help="Show what would move without changing anything.")
    args = parser.parse_args(argv)

    if not args.dry_run and server_is_running():
        print(f"The LangGraph server is running on port {SERVER_PORT}. Stop it first so its data isn't copied mid-write.", file=sys.stderr)
        return 1
    print(f"Runtime folder: {state_dir()}")
    report = []
    for source, destination in planned_moves(args.checkout.resolve()):
        report += move(source, destination, args.dry_run)
    report += remove_empty_legacy_dirs(args.checkout.resolve(), args.dry_run)
    print("\n".join(report) if report else "Nothing to migrate.")
    return 1 if any(line.startswith("SKIPPED") for line in report) else 0


if __name__ == "__main__":
    sys.exit(main())
