"""Unattended orchestrator: apply human decisions, close confirmed-stale items, propose new items, post a summary.

`--mode apply` makes no LLM calls (apply + cleanup only). `--mode full` also proposes new items.
Exit codes: 0 success, 1 health failure (e.g. a scrape returned nothing), 2 LinkedIn login needed.
Nothing is clicked on LinkedIn without a human decision in Agent Inbox, and no message is ever sent.
"""

import argparse
import asyncio
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

import inbox_manager
import invitations_manager
from linkedin_guard import blocked_write_summary
from unattended import HealthCheckError, LoginRequiredError, ReviewCounts, notify

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
    for name in ("daily_run", "invitations_manager", "inbox_manager", "unattended"):
        logging.getLogger(name).addHandler(handler)
        logging.getLogger(name).setLevel(logging.INFO)


def build_summary(proposed: ReviewCounts, warnings: list[str]) -> str:
    text = f"{proposed.new} new items in Agent Inbox ({proposed.needs_judgment} need judgment)"
    if proposed.cap_hit:
        text += ", safety cap hit"
    if warnings:
        text += f", {len(warnings)} warning(s): " + "; ".join(warnings)
    return text


async def run(mode: str, headless: bool) -> int:
    warnings: list[str] = []
    proposed = ReviewCounts()
    exit_code = EXIT_OK

    steps = [
        ("invitations apply+cleanup", lambda: invitations_manager.process_linkedin_invitations(headless=headless, apply_inbox_decisions=True, cleanup_stale=True, unattended=True)),
        ("messages cleanup", lambda: inbox_manager.manage_linkedin_inbox(headless=headless, unattended=True, cleanup_only=True)),
    ]
    if mode == "full":
        steps += [
            ("invitations propose", lambda: invitations_manager.process_linkedin_invitations(headless=headless, unattended=True)),
            ("messages propose", lambda: inbox_manager.manage_linkedin_inbox(headless=headless, unattended=True)),
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
    summary = build_summary(proposed, warnings)
    logger.info("Summary: %s", summary)
    if mode == "full" or warnings:
        notify("LinkedIn agent", summary)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the LinkedIn agents unattended.")
    parser.add_argument("--mode", choices=["full", "apply"], default="full", help="full: apply, cleanup, propose, summary. apply: apply and cleanup only (no LLM calls).")
    parser.add_argument("--headless", action="store_true", help="Run the browser in headless mode.")
    parser.add_argument("--model-backend", choices=["ollama", "openai", "azure", "fallback"], default=None, help="Model backend for the full run (default: MODEL_BACKEND env var).")
    args = parser.parse_args()

    configure_file_logging()
    if args.model_backend:
        if args.model_backend != invitations_manager.MODEL_BACKEND:
            invitations_manager.agent = invitations_manager.build_agent(args.model_backend)
        if args.model_backend != inbox_manager.MODEL_BACKEND:
            inbox_manager.model = inbox_manager.build_model(args.model_backend)
    return asyncio.run(run(args.mode, args.headless))


if __name__ == "__main__":
    sys.exit(main())
