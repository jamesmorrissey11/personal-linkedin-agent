"""Capture sanitized LinkedIn conversation markup for selector regression tests."""

import argparse
import asyncio
import html
import logging
import re
from pathlib import Path

from linkedin_guard import blocked_writes, reset_blocked_writes, safe_click
from linkedin_pages import extract_conversation_messages, get_logged_in_user_name, open_linkedin

logger = logging.getLogger("capture_linkedin_fixtures")

REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "playwright" / "fixtures"
CONVERSATION_DETAIL_SELECTOR = "main .scaffold-layout__detail"
ARCHIVED_FILTER_SELECTOR = "[data-test-messaging-inbox-filters__folder-pill]"
CONVERSATION_MENU_SELECTORS = [
    f"{CONVERSATION_DETAIL_SELECTOR} button.msg-thread-actions__control",
    "button[aria-label*='conversation options' i]",
    "button[aria-label*='more actions' i]",
    "button[aria-label*='more options' i]",
    "button.msg-thread-actions__control",
]
PRIVATE_TEXT_SELECTORS = [
    ".msg-s-message-group__name",
    ".msg-s-message-group__profile-link",
    "p.msg-s-event-listitem__body",
    ".msg-thread__link-to-profile",
    ".msg-entity-lockup__entity-title",
    "main h1",
    "main h2",
]
LINKEDIN_URN_PATTERN = re.compile(r"urn:li:[^\"'<>\\s]+", re.IGNORECASE)


def sanitize_html(markup: str, private_values: set[str]) -> str:
    """Replace observed names/message text and LinkedIn URNs with stable placeholders."""
    sanitized = markup
    for value in sorted((value.strip() for value in private_values if value and value.strip()), key=len, reverse=True):
        for representation in {value, html.escape(value, quote=False), html.escape(value, quote=True)}:
            sanitized = sanitized.replace(representation, "[NAME_OR_MESSAGE]")
    return LINKEDIN_URN_PATTERN.sub("[LINKEDIN_URN]", sanitized)


async def _open_conversation_menu(page) -> str:
    for selector in CONVERSATION_MENU_SELECTORS:
        for element in await page.query_selector_all(selector):
            if await element.is_visible() and await safe_click(element):
                await page.wait_for_timeout(500)
                return selector
    raise RuntimeError("Could not find the conversation options button; inspect the live markup and add a fallback selector.")


async def _private_values(page) -> set[str]:
    values = {await get_logged_in_user_name(page)}
    for message in await extract_conversation_messages(page, "fixture participant"):
        values.update({message.author, message.content})
    for selector in PRIVATE_TEXT_SELECTORS:
        for value in await page.locator(selector).all_inner_texts():
            if value.strip():
                values.add(value.strip())
    return values


async def _fixture_markup(page, *, include_archived_indicator: bool) -> str:
    detail = await page.locator(CONVERSATION_DETAIL_SELECTOR).first.evaluate("element => element.outerHTML")
    archived_indicator = ""
    if include_archived_indicator:
        archived_indicator = await page.locator(ARCHIVED_FILTER_SELECTOR).first.evaluate("element => element.outerHTML")
    return f"<!doctype html><html><body>{archived_indicator}{detail}</body></html>"


async def capture_conversation(page, url: str, output_path: Path, *, include_archived_indicator: bool) -> None:
    await page.goto(url, wait_until="domcontentloaded")
    await page.wait_for_timeout(2000)
    menu_selector = await _open_conversation_menu(page)
    private_values = await _private_values(page)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(sanitize_html(await _fixture_markup(page, include_archived_indicator=include_archived_indicator), private_values))
    logger.info("Captured %s using menu selector %s", output_path, menu_selector)


async def capture_fixtures(ordinary_url: str, archived_url: str) -> None:
    reset_blocked_writes()
    async with open_linkedin(headless=True, unattended=True) as (_, page):
        await capture_conversation(page, ordinary_url, FIXTURE_DIR / "conversation_thread.html", include_archived_indicator=False)
        await capture_conversation(page, archived_url, FIXTURE_DIR / "conversation_archived.html", include_archived_indicator=True)
    ui_blocks = [event for event in blocked_writes() if event.layer == "ui"]
    if ui_blocks:
        raise RuntimeError(f"Fixture capture triggered blocked UI actions: {ui_blocks}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ordinary_url", help="LinkedIn URL for a conversation in the main inbox")
    parser.add_argument("archived_url", help="LinkedIn URL for a conversation in the Archived filter")
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = parse_args()
    asyncio.run(capture_fixtures(args.ordinary_url, args.archived_url))


if __name__ == "__main__":
    main()
