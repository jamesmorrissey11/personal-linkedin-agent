"""Shared runtime helpers: errors, report counts, console logging, and macOS notifications."""

import asyncio
import logging
import subprocess
import sys
from dataclasses import dataclass

logger = logging.getLogger("unattended")


def configure_console_logging() -> None:
    """Rich console logging for CLI runs; called once at startup, never at import."""
    from rich.logging import RichHandler

    logging.basicConfig(level=logging.WARNING, format="%(message)s", datefmt="[%X]", handlers=[RichHandler(show_level=True)])


# Stop scanning once this many consecutive items are already known (queued, applied, superseded, or self-replied).
KNOWN_STREAK_STOP = 5


class LoginRequiredError(RuntimeError):
    """The cached LinkedIn session expired and no human is available to log in."""


class HealthCheckError(RuntimeError):
    """A scrape looked broken (e.g. zero cards), so the result can't be trusted and nothing is closed."""


@dataclass
class ReviewCounts:
    """Split counts for one run so already-handled items are never double counted."""

    new: int = 0
    already_queued: int = 0
    applied: int = 0
    superseded: int = 0
    needs_judgment: int = 0
    cap_hit: bool = False

    @property
    def total(self) -> int:
        return self.new + self.already_queued + self.applied + self.superseded

    def __add__(self, other: "ReviewCounts") -> "ReviewCounts":
        return ReviewCounts(
            self.new + other.new,
            self.already_queued + other.already_queued,
            self.applied + other.applied,
            self.superseded + other.superseded,
            self.needs_judgment + other.needs_judgment,
            self.cap_hit or other.cap_hit,
        )

    def describe(self) -> str:
        text = f"{self.new} new, {self.already_queued} already queued, {self.applied} applied, {self.superseded} superseded ({self.total} total; {self.needs_judgment} need judgment)"
        return text + " - SAFETY CAP HIT, increase the limit" if self.cap_hit else text


def notify(title: str, message: str) -> None:
    """Post a macOS notification; on other platforms (or on failure) only log it."""
    logger.info("NOTIFY %s: %s", title, message)
    if sys.platform != "darwin":
        return
    script = ["on run argv", "display notification (item 1 of argv) with title (item 2 of argv)", "end run"]
    command = ["osascript"] + [part for line in script for part in ("-e", line)] + [message, title]
    try:
        subprocess.run(command, check=False, timeout=10, capture_output=True)
    except (OSError, subprocess.SubprocessError) as error:
        logger.warning("Could not post notification: %s", error)


async def notify_async(title: str, message: str) -> None:
    """Post a notification from async code without blocking the event loop.

    notify() shells out to osascript. Called directly from a graph node that would be a blocking
    subprocess call on the event loop, which `langgraph dev`'s blockbuster turns into an error that
    aborts the run. Notifications are also best-effort: a failure here must never fail an action that
    already took effect on LinkedIn.
    """
    try:
        await asyncio.to_thread(notify, title, message)
    except Exception as error:
        logger.warning("Could not post notification: %s", error)
