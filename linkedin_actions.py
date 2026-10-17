"""Human-approved LinkedIn actions driven by Agent Inbox review graphs."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from linkedin_guard import ApprovedAction, safe_click
from linkedin_pages import UNKNOWN_AUTHORS, ConversationMessage, LinkedInBusyError, collect_invitation_profiles, extract_conversation_messages, get_invitation_cards, get_invitation_info, get_logged_in_user_name, open_linkedin
from unattended import LoginRequiredError

COMPOSER_SELECTORS = [
    ".msg-form__contenteditable[contenteditable='true']",
    "div[role='textbox'][aria-label*='Write a message']",
]
SEND_BUTTON_SELECTORS = [
    "button.msg-form__send-button",
    "form button[type='submit']:has-text('Send')",
]
CONVERSATION_MENU_SELECTORS = [
    "main .scaffold-layout__detail button.msg-thread-actions__control",
    "button.msg-thread-actions__control.artdeco-button--2",
]
ARCHIVE_MENU_ITEM_SELECTORS = [
    "[data-view-name='message-toolbar-dropdown-toggle-archive']:has-text('Archive')",
    ".msg-thread-actions__dropdown-option:has-text('Archive')",
]
ARCHIVED_INDICATOR_SELECTORS = [
    "[data-test-messaging-inbox-filters__folder-pill]:has-text('Archived')",
    ".msg-cross-pillar-inbox-filters-v3__drop-down-trigger:has-text('Archived')",
    "[data-view-name='message-toolbar-dropdown-toggle-archive']:has-text('Restore')",
]

LOCK_TIMEOUT_SECONDS = 300
INVITATION_MANAGER_URL = "https://www.linkedin.com/mynetwork/invitation-manager/"
NEW_MESSAGE_NOTE = "A new message arrived since this was queued; nothing was sent. Review it and choose again."
ALREADY_REPLIED_NOTE = "You already replied on LinkedIn; nothing was sent. Send this too by choosing again, or Ignore."

logger = logging.getLogger("linkedin_actions")


@dataclass
class ActionResult:
    outcome: Literal["accepted", "ignored", "sent", "archived", "superseded"] | None
    error: str | None = None
    latest_message: str | None = None


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n")
    return "\n".join(line.rstrip() for line in normalized.split("\n")).rstrip()


def same_profile(a: str, b: str) -> bool:
    left = urlparse(a)
    right = urlparse(b)
    return (left.scheme.casefold(), (left.hostname or "").casefold(), left.path.rstrip("/")) == (
        right.scheme.casefold(),
        (right.hostname or "").casefold(),
        right.path.rstrip("/"),
    )


def message_precheck(
    messages: list[ConversationMessage],
    logged_in_user: str,
    expected_latest: str,
    action: str,
    reply: str,
) -> tuple[Literal["proceed", "already_sent", "stop"], str | None]:
    if not messages:
        return "stop", NEW_MESSAGE_NOTE
    latest = messages[-1]
    user_name = logged_in_user.strip().casefold()
    author = latest.author.strip().casefold()
    from_user = user_name not in UNKNOWN_AUTHORS and author not in UNKNOWN_AUTHORS and author == user_name
    latest_text = normalize_text(latest.content)
    if action == "reply" and from_user and latest_text == normalize_text(reply):
        return "already_sent", None
    if latest_text == normalize_text(expected_latest):
        return "proceed", None
    if action == "dismiss" and from_user:
        return "proceed", None
    if action == "reply" and from_user:
        return "stop", ALREADY_REPLIED_NOTE
    return "stop", NEW_MESSAGE_NOTE


async def _first_visible(page, selectors):
    for selector in selectors:
        locator = page.locator(selector)
        for index in range(await locator.count()):
            candidate = locator.nth(index)
            if await candidate.is_visible():
                return candidate
    return None


async def click_invitation_button(card, decision: Literal["accept", "ignore"]) -> bool:
    button = await card.query_selector(f"button[aria-label*='{decision.title()}']")
    if not button:
        logger.warning("%s button not found on the invitation card.", decision.title())
        return False
    return await safe_click(button, approval=ApprovedAction("invitation", decision))


async def _composer_text(composer) -> str:
    return await composer.evaluate(
        """element => Array.from(element.childNodes)
            .map(node => node.nodeName === "BR" ? "\\n" : (node.innerText ?? node.textContent ?? ""))
            .join("\\n")"""
    )


async def send_reply(page, text: str) -> bool:
    composer = await _first_visible(page, COMPOSER_SELECTORS)
    if composer is None:
        return False
    await composer.fill(text)
    if normalize_text(await _composer_text(composer)) != normalize_text(text):
        await composer.fill("")
        return False
    send_button = await _first_visible(page, SEND_BUTTON_SELECTORS)
    if send_button is None:
        await composer.fill("")
        return False
    return await safe_click(send_button, approval=ApprovedAction("message", "send"))


async def archive_conversation(page) -> bool:
    approval = ApprovedAction("message", "archive")
    archive_item = await _first_visible(page, ARCHIVE_MENU_ITEM_SELECTORS)
    if archive_item is None:
        menu = await _first_visible(page, CONVERSATION_MENU_SELECTORS)
        if menu is None or not await safe_click(menu, approval=approval):
            return False
        await page.wait_for_timeout(300)
        archive_item = await _first_visible(page, ARCHIVE_MENU_ITEM_SELECTORS)
    return archive_item is not None and await safe_click(archive_item, approval=approval)


async def conversation_is_archived(page) -> bool | None:
    if await _first_visible(page, ARCHIVED_INDICATOR_SELECTORS) is not None:
        return True
    if await _first_visible(page, CONVERSATION_MENU_SELECTORS) is not None or await _first_visible(page, COMPOSER_SELECTORS) is not None:
        return False
    return None


async def _find_invitation_card(page, profile_url: str):
    for card in await get_invitation_cards(page):
        invitation = await get_invitation_info(card)
        if invitation and same_profile(invitation.profile, profile_url):
            return card
    return None


async def perform_invitation_action(profile_url: str, decision: Literal["accept", "ignore"]) -> ActionResult:
    approval = ApprovedAction("invitation", decision)
    try:
        async with open_linkedin(headless=True, unattended=True, approval=approval, lock_timeout=LOCK_TIMEOUT_SECONDS) as (_, page):
            await page.goto(INVITATION_MANAGER_URL)
            card = await _find_invitation_card(page, profile_url)
            if card is None:
                profiles, complete = await collect_invitation_profiles(page)
                if not any(same_profile(profile, profile_url) for profile in profiles):
                    result = ActionResult("superseded") if complete else ActionResult(None, "Couldn't find this invitation on LinkedIn; it may still be loading. Try again.")
                    logger.info("Invitation action item=%s action=%s result=%s", profile_url, decision, result.outcome or result.error)
                    return result
                card = await _find_invitation_card(page, profile_url)
            if card is None or not await click_invitation_button(card, decision):
                return ActionResult(None, "Couldn't complete the invitation action. Check LinkedIn before trying again.")
            await page.wait_for_timeout(500)
            if await _find_invitation_card(page, profile_url) is not None:
                return ActionResult(None, "Couldn't confirm the invitation action. Check LinkedIn before trying again.")
            result = ActionResult("accepted" if decision == "accept" else "ignored")
            logger.info("Invitation action item=%s action=%s result=%s", profile_url, decision, result.outcome)
            return result
    except LoginRequiredError:
        return ActionResult(None, "LinkedIn login expired. Log in with a visible browser, then try again.")
    except LinkedInBusyError:
        return ActionResult(None, "Another LinkedIn task is running; try again in a few minutes.")
    except Exception as error:
        logger.exception("Invitation action failed item=%s action=%s", profile_url, decision)
        return ActionResult(None, f"Couldn't complete the action: {error}")


async def _sent_reply_is_visible(page, reply: str, logged_in_user: str) -> bool:
    for _ in range(15):
        messages = await extract_conversation_messages(page, "conversation participant")
        if messages:
            latest = messages[-1]
            if latest.author.strip().casefold() == logged_in_user.strip().casefold() and normalize_text(latest.content) == normalize_text(reply):
                return True
        await asyncio.sleep(1)
    return False


async def perform_message_action(
    conversation_url: str,
    action: Literal["reply", "dismiss"],
    reply: str,
    expected_latest: str,
) -> ActionResult:
    if action == "reply" and not reply.strip():
        return ActionResult(None, "The reply is empty; nothing was sent.")
    approval = ApprovedAction("message", "send" if action == "reply" else "archive")
    reply_hash = hashlib.sha256(reply.encode()).hexdigest()[:12] if action == "reply" else None
    try:
        async with open_linkedin(headless=True, unattended=True, approval=approval, lock_timeout=LOCK_TIMEOUT_SECONDS) as (_, page):
            await page.goto(conversation_url)
            messages = await extract_conversation_messages(page, "conversation participant")
            logged_in_user = await get_logged_in_user_name(page)
            verdict, note = message_precheck(messages, logged_in_user, expected_latest, action, reply)
            latest_message = messages[-1].content if messages else None
            if verdict == "already_sent":
                result = ActionResult("sent")
            elif verdict == "stop":
                result = ActionResult(None, note, latest_message)
            elif action == "dismiss":
                result = ActionResult("archived") if await archive_conversation(page) else ActionResult(None, "Couldn't archive the conversation. Check LinkedIn before trying again.")
            elif not await send_reply(page, reply):
                result = ActionResult(None, "LinkedIn's message box didn't match your reply; nothing was sent.")
            elif await _sent_reply_is_visible(page, reply, logged_in_user):
                result = ActionResult("sent")
            else:
                result = ActionResult(None, "Couldn't confirm the message was sent. Check LinkedIn before trying again.")
            logger.info(
                "Message action item=%s action=%s reply_sha256=%s result=%s",
                conversation_url,
                action,
                reply_hash or "n/a",
                result.outcome or result.error,
            )
            return result
    except LoginRequiredError:
        return ActionResult(None, "LinkedIn login expired. Log in with a visible browser, then try again.")
    except LinkedInBusyError:
        return ActionResult(None, "Another LinkedIn task is running; try again in a few minutes.")
    except Exception as error:
        logger.exception("Message action failed item=%s action=%s reply_sha256=%s", conversation_url, action, reply_hash or "n/a")
        return ActionResult(None, f"Couldn't complete the action: {error}")
