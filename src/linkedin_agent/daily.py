"""Unattended orchestrator: recover reviews, sync handled items, propose new items, and post a summary.

Exit codes: 0 success, 1 health failure (e.g. a scrape returned nothing), 2 LinkedIn login needed.
The daily run never writes to LinkedIn; live actions happen inside the review graphs after a human decision.
"""

import argparse
import asyncio
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from linkedin_agent import inbox, invitations
from linkedin_agent.linkedin.guard import blocked_write_summary
from linkedin_agent.review.graphs import GRAPH_ID, MESSAGE_GRAPH_ID
from linkedin_agent.review.queue import get_review_client, recover_stuck_reviews, retire_legacy_reviews
from linkedin_agent.runtime import HealthCheckError, LoginRequiredError, ReviewCounts, notify

logger = logging.getLogger("daily_run")

EXIT_OK = 0
EXIT_HEALTH = 1
EXIT_LOGIN = 2
LOG_PATH = Path("logs/daily_run.log")


def configure_file_logging() -> None:
    LOG_PATH.parent.mkdir(exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=1_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.setLevel(logging.INFO)
    for name in ("daily_run", "invitations_manager", "inbox_manager", "unattended", "llm"):
        logging.getLogger(name).addHandler(handler)
        logging.getLogger(name).setLevel(logging.INFO)


def build_summary(proposed: ReviewCounts, warnings: list[str], recovered: int = 0, retired: int = 0) -> str:
    text = f"{proposed.new} new items in Agent Inbox ({proposed.needs_judgment} need judgment)"
    if proposed.cap_hit:
        text += ", safety cap hit"
    if recovered:
        text += f", {recovered} interrupted action(s) brought back for review"
    if retired:
        text += f", {retired} old decision(s) from before live actions were retired; anything still open on LinkedIn was queued again"
    if warnings:
        text += f", {len(warnings)} warning(s): " + "; ".join(warnings)
    return text


async def recover_and_retire_reviews() -> tuple[int, int]:
    client = get_review_client()
    now = datetime.now(timezone.utc)
    recovered = 0
    retired = 0
    for graph_id in (GRAPH_ID, MESSAGE_GRAPH_ID):
        recovered += await recover_stuck_reviews(client, graph_id, now)
        retired += await retire_legacy_reviews(client, graph_id)
    return recovered, retired


async def run(headless: bool) -> int:
    warnings: list[str] = []
    proposed = ReviewCounts()
    exit_code = EXIT_OK
    recovered = 0
    retired = 0

    logger.info("=== Step: recover + retire legacy ===")
    try:
        recovered, retired = await recover_and_retire_reviews()
    except Exception as error:
        logger.exception("recover + retire legacy failed")
        warnings.append(f"recover + retire legacy: {error!r}")
        exit_code = EXIT_HEALTH
    steps = [
        ("invitations cleanup", lambda: invitations.process_linkedin_invitations(headless=headless, cleanup_stale=True, unattended=True)),
        ("messages cleanup", lambda: inbox.manage_linkedin_inbox(headless=headless, unattended=True, cleanup_only=True)),
        ("invitations propose", lambda: invitations.process_linkedin_invitations(headless=headless, unattended=True)),
        ("messages propose", lambda: inbox.manage_linkedin_inbox(headless=headless, unattended=True)),
    ]

    for name, step in steps:
        logger.info("=== Step: %s ===", name)
        try:
            counts = await step()
        except LoginRequiredError as error:
            logger.error("%s: %s", name, error)
            notify("LinkedIn login needed", "Your LinkedIn session expired. Log in with a visible browser, then re-run.")
            return EXIT_LOGIN
        except HealthCheckError as error:
            logger.error("%s: health check failed: %s", name, error)
            warnings.append(f"{name}: {error}")
            exit_code = EXIT_HEALTH
            continue
        except Exception as error:
            logger.exception("%s failed", name)
            warnings.append(f"{name}: {error!r}")
            exit_code = EXIT_HEALTH
            continue
        logger.info("%s: %s", name, counts.describe())
        if "propose" in name:
            proposed = proposed + counts

    if blocked := blocked_write_summary():
        warnings.append(blocked)
    summary = build_summary(proposed, warnings, recovered, retired)
    logger.info("Summary: %s", summary)
    notify("LinkedIn agent", summary)
    return exit_code


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--headless", action="store_true", help="Run the browser in headless mode.")


def run_command(args: argparse.Namespace) -> int:
    configure_file_logging()
    invitations.configure(args.model_backend)
    inbox.configure(args.model_backend)
    return asyncio.run(run(args.headless))
