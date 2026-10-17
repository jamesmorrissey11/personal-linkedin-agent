"""Read-only LinkedIn page helpers: invitation and conversation scraping, with their selector fallback chains.

Importable without the LLM stack (no pydantic_ai, openai, or azure) so the review graphs can drive LinkedIn.
"""

import asyncio
import logging
import os
from urllib.parse import unquote, urlparse, urlunparse

from playwright.async_api import ElementHandle, Page

from linkedin_agent.linkedin.models import ConversationMessage, Invitation

logger = logging.getLogger("linkedin_pages")
logger.setLevel(logging.INFO)

MAX_SCANNED_INVITATIONS = int(os.environ.get("MAX_SCANNED_INVITATIONS", "500"))
NO_PENDING_INVITATIONS_TEXT = "no pending invitations"
# Fallback chain: LinkedIn's current invitation manager says "No new invitations" (seen 2026-10-17).
NO_PENDING_INVITATIONS_TEXTS = (NO_PENDING_INVITATIONS_TEXT, "no new invitations")
INVITATION_CARD_SELECTORS = [
    "div[role='listitem']:has(button[aria-label^='Ignore an invitation to connect from ']):has(a[href*='/in/'])",
    "main div[componentkey^='auto-component-']:has(button[aria-label*='Accept'])",
]


UNKNOWN_AUTHORS = {"", "unknown", "unknown user"}


# --- invitations -----------------------------------------------------------


async def get_invitation_info(card) -> Invitation | None:
    def first_non_empty_line(text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return text.strip()

    # Fetch the primary profile link (most cards link to /in/ profiles)
    profile_link_element = await card.query_selector("a[href*='/in/']")
    if not profile_link_element:
        profile_link_element = await card.query_selector("a")
    if not profile_link_element:
        return None

    profile_link = await profile_link_element.get_attribute("href")
    if not profile_link:
        return None
    if not profile_link.startswith("http"):
        profile_link = f"https://www.linkedin.com{profile_link}"
    # Normalize URL: decode any percent-encoded characters to get clean URL
    parsed = urlparse(profile_link)
    decoded_path = unquote(parsed.path)
    profile_link = urlunparse(parsed._replace(path=decoded_path))

    # Resolve the invitee name from a list of possible selectors (new follower layout lacks <strong>)
    name_selectors = [
        "a > strong",
        "a span[aria-hidden='true']",
        "span[aria-hidden='true']",
        "span[dir='auto']",
    ]
    name = ""
    for selector in name_selectors:
        element = await card.query_selector(selector)
        if element:
            text = (await element.inner_text()).strip()
            if text:
                name = first_non_empty_line(text)
                break
    if not name:
        link_text = (await profile_link_element.inner_text()).strip()
        if link_text:
            name = first_non_empty_line(link_text)
    if not name:
        return None

    card_lines = [line.strip() for line in (await card.inner_text()).splitlines() if line.strip()]
    try:
        name_index = card_lines.index(name)
    except ValueError:
        name_index = -1

    job_title = "Unknown"
    for line in card_lines[name_index + 1 :]:
        if line in {"Accept", "Ignore"} or line.startswith("Reply to ") or "mutual connection" in line.lower():
            continue
        if line:
            job_title = line
            break

    if job_title == "Unknown":
        for selector in ["p:nth-of-type(2)", "span.t-14", "div.artdeco-entity-lockup__subtitle span"]:
            element = await card.query_selector(selector)
            if not element:
                continue
            text = (await element.inner_text()).strip()
            if text:
                job_title = first_non_empty_line(text)
                break

    # Check for mutual connections (single phrase)
    connection_info_element = await card.query_selector("*:has-text('mutual connection')")
    connection_info = (await connection_info_element.inner_text()).strip() if connection_info_element else ""
    has_mutual_connections = "mutual connection" in connection_info.lower()

    return Invitation(name=name, profile=profile_link, job_title=job_title, mutual_connections=has_mutual_connections)


async def get_invitation_cards(page: Page) -> list[ElementHandle]:
    for selector in INVITATION_CARD_SELECTORS:
        cards = await page.query_selector_all(selector)
        if cards:
            return cards
    html_snippet = (await page.content())[:2000]
    logger.warning("No invitation cards found. HTML snippet (2k chars): %s", html_snippet)
    return []


async def page_reports_no_invitations(page: Page) -> bool:
    content = (await page.content()).lower()
    return any(text in content for text in NO_PENDING_INVITATIONS_TEXTS)


async def collect_invitation_profiles(page: Page) -> tuple[set[str], bool]:
    """Scroll the whole invitation list. Returns (profiles, complete); complete is False if any card could not be parsed or a cap was hit."""
    profiles: set[str] = set()
    complete = True
    consecutive_no_new_scrolls = 0
    while consecutive_no_new_scrolls < 5:
        found_new = False
        for card in await get_invitation_cards(page):
            invitation = await get_invitation_info(card)
            if not invitation:
                complete = False
                continue
            if invitation.profile not in profiles:
                profiles.add(invitation.profile)
                found_new = True
        if len(profiles) >= MAX_SCANNED_INVITATIONS:
            return profiles, False
        consecutive_no_new_scrolls = 0 if found_new else consecutive_no_new_scrolls + 1
        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.9)")
        await asyncio.sleep(2)
    return profiles, complete


# --- messages --------------------------------------------------------------


def is_linkedin_conversation_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and parsed.hostname in {"linkedin.com", "www.linkedin.com"} and parsed.path.startswith("/messaging/")


SELF_PROFILE_URL = "https://www.linkedin.com/in/me/"
LINKEDIN_TITLE_SUFFIX = "| LinkedIn"

# Scoped to the logged-in user's own nav avatar. Never widen these to bare "a[href*='/in/'] img[alt]":
# on the messaging page that matches a conversation participant, which would make the agent think
# someone else's message was the user's own.
ME_AVATAR_SELECTORS = (
    ".global-nav__primary-link-me-menu-trigger img[alt]",
    "button[aria-label='Open profile menu'] img[alt]",
    ".global-nav__me-photo",
)


async def _name_from_nav(page: Page) -> str | None:
    """Read the user's display name out of the top nav without clicking anything."""
    for selector in ME_AVATAR_SELECTORS:
        element = await page.query_selector(selector)
        if not element:
            continue
        alt_text = (await element.get_attribute("alt") or "").strip()
        if alt_text and alt_text.casefold() not in UNKNOWN_AUTHORS:
            return alt_text

    profile_button = await page.query_selector("button[aria-label*='View profile for']")
    if profile_button:
        aria_label = await profile_button.get_attribute("aria-label") or ""
        name = aria_label.replace("View profile for", "").strip()
        if name and name.casefold() not in UNKNOWN_AUTHORS:
            return name

    return None


async def _name_from_self_profile(page: Page) -> str | None:
    """Resolve the name via /in/me/, which redirects to the user's own profile.

    The newer React surfaces drop the global-nav identity hooks entirely, so this is the dependable
    fallback. The profile <h1> renders lazily and is empty on load, but the document title is always
    "<Display Name> | LinkedIn" and matches the author strings used in conversations. The original
    page is restored so callers see no navigation side effect.
    """
    if "linkedin.com" not in page.url:
        return None

    original_url = page.url
    try:
        await page.goto(SELF_PROFILE_URL)
        await page.wait_for_load_state("load")
        # A signed-out session bounces to a login/auth wall instead of a profile.
        if "/in/" not in page.url:
            return None
        title = (await page.title() or "").strip()
    finally:
        try:
            await page.goto(original_url)
        except Exception as e:
            logger.warning(f"Could not return to {original_url} after reading the profile name: {e}")

    if not title.endswith(LINKEDIN_TITLE_SUFFIX):
        return None
    name = title[: -len(LINKEDIN_TITLE_SUFFIX)].strip()
    if not name or name.casefold() in UNKNOWN_AUTHORS:
        return None
    return name


async def get_logged_in_user_name(page: Page) -> str:
    """Return the logged-in user's display name, or "Unknown User" when it cannot be established.

    The inbox workflow compares this against each conversation's latest author, so a wrong name is worse
    than no name: "Unknown User" merely keeps every conversation queued for review, while a
    participant's name would hide threads that still need a reply. Every lookup is therefore scoped
    to the user's own identity, and anything ambiguous fails closed.
    """
    try:
        return await _name_from_nav(page) or await _name_from_self_profile(page) or "Unknown User"
    except Exception as e:
        logger.warning(f"Could not extract logged-in user name: {e}")
        return "Unknown User"


def latest_message_is_from_user(messages: list[ConversationMessage], logged_in_user: str) -> bool:
    """True only when the latest author exactly matches the user; any ambiguity returns False so the item is kept."""
    if not messages or logged_in_user.strip().casefold() in UNKNOWN_AUTHORS:
        return False
    author = messages[-1].author.strip().casefold()
    return author not in UNKNOWN_AUTHORS and author == logged_in_user.strip().casefold()


async def extract_conversation_messages(page: Page, sender_name: str) -> list[ConversationMessage]:
    """Extract the last three messages of the open conversation."""
    last_three_messages: list[ConversationMessage] = []
    try:
        message_elements = await page.query_selector_all("li.msg-s-message-list__event")
        # LinkedIn only prints the author name on the first message of a consecutive group, so carry it forward.
        current_author = "Unknown"
        authored: list[tuple[str, object]] = []
        for msg_element in message_elements:
            author_element = await msg_element.query_selector(".msg-s-message-group__name")
            if not author_element:
                author_element = await msg_element.query_selector("a .msg-s-message-group__profile-link")
            if author_element:
                name = (await author_element.inner_text()).strip()
                if name:
                    current_author = name
            authored.append((current_author, msg_element))

        for author, msg_element in authored[-3:]:
            try:
                content_element = await msg_element.query_selector("p.msg-s-event-listitem__body")
                content = await content_element.inner_text() if content_element else "No content"

                timestamp_element = await msg_element.query_selector("time.msg-s-message-group__timestamp")
                if not timestamp_element:
                    timestamp_element = await msg_element.query_selector("time.msg-s-message-list__time-heading")
                timestamp = await timestamp_element.inner_text() if timestamp_element else "Unknown time"

                last_three_messages.append(ConversationMessage(author=author, content=content.strip(), timestamp=timestamp.strip()))
            except Exception as e:
                logger.warning(f"Error extracting individual message: {e}")
                continue
        logger.info(f"Extracted {len(last_three_messages)} messages for {sender_name}")
    except Exception as e:
        logger.warning(f"Could not extract messages for {sender_name}: {e}")
        last_three_messages.append(ConversationMessage(author=sender_name, content="Could not extract message content", timestamp="Unknown"))
    return last_three_messages
