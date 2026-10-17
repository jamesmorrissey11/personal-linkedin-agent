"""Human-approved LinkedIn actions driven by Agent Inbox review graphs."""

import asyncio
import hashlib
import logging
from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlparse

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from linkedin_agent.linkedin.guard import ApprovedAction, safe_click
from linkedin_agent.linkedin.models import ConversationMessage
from linkedin_agent.linkedin.pages import UNKNOWN_AUTHORS, collect_invitation_profiles, extract_conversation_messages, get_invitation_cards, get_invitation_info, get_logged_in_user_name, page_reports_no_invitations
from linkedin_agent.linkedin.session import LinkedInBusyError, open_linkedin
from linkedin_agent.runtime import LoginRequiredError

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

CONVERSATION_MESSAGE_SELECTOR = "li.msg-s-message-list__event"
SEND_WRITE_MARKER = "action=createMessage"
ARCHIVE_WRITE_MARKER = "action=addCategory"
# Confirmed against live traffic (2026-10-17): accept/ignore POST a server-driven-UI request
# (sduiid=com.linkedin.sdui.requests.mynetwork.addaInvitationAction); the voyager endpoint is the older UI's.
INVITATION_WRITE_MARKERS = ("InvitationAction", "voyagerRelationshipsDashInvitations")
INVITATION_LIST_SETTLE_MS = 3000

LOCK_TIMEOUT_SECONDS = 300
CONVERSATION_LOAD_TIMEOUT_MS = 20000
CONVERSATION_SETTLE_MS = 1500
WRITE_CONFIRM_TIMEOUT_MS = 15000
INVITATION_MANAGER_URL = "https://www.linkedin.com/mynetwork/invitation-manager/"
NEW_MESSAGE_NOTE = "A new message arrived since this was queued; nothing was sent. Review it and choose again."
ALREADY_REPLIED_NOTE = "You already replied on LinkedIn; nothing was sent. Send this too by choosing again, or Ignore."
CONVERSATION_NOT_LOADED_NOTE = "Couldn't load the conversation on LinkedIn; nothing was sent or archived. Try again."

logger = logging.getLogger("linkedin_actions")


@dataclass
class ActionResult:
    outcome: Literal["accepted", "ignored", "sent", "archived", "superseded"] | None
    error: str | None = None
    latest_message: str | None = None


def normalize_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n")
    return "\n".join(line.rstrip() for line in normalized.replace("\xa0", " ").split("\n")).rstrip()


def comparable_text(text: str) -> str:
    """Whitespace-insensitive form for matching a message against how LinkedIn re-renders it."""
    return " ".join(text.replace("\xa0", " ").split())


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
    latest_text = comparable_text(latest.content)
    if action == "reply" and from_user and latest_text == comparable_text(reply):
        return "already_sent", None
    if latest_text == comparable_text(expected_latest):
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


async def _invitation_button(card, decision: Literal["accept", "ignore"]):
    button = await card.query_selector(f"button[aria-label*='{decision.title()}']")
    if not button:
        logger.warning("%s button not found on the invitation card.", decision.title())
    return button


async def click_invitation_button(card, decision: Literal["accept", "ignore"]) -> bool:
    button = await _invitation_button(card, decision)
    return button is not None and await safe_click(button, approval=ApprovedAction("invitation", decision))


# LinkedIn's composer renders each line as <p>, blank lines as <p><br></p>, and repeated spaces as &nbsp;.
COMPOSER_TEXT_JS = """element => {
    const lines = [];
    let current = null;
    for (const node of element.childNodes) {
        if (node.nodeName === "BR") {
            lines.push(current ?? "");
            current = null;
        } else if (node.nodeName === "P" || node.nodeName === "DIV") {
            if (current !== null) lines.push(current);
            current = null;
            lines.push(node.textContent ?? "");
        } else {
            current = (current ?? "") + (node.textContent ?? "");
        }
    }
    if (current !== null) lines.push(current);
    return lines.join("\\n").replace(/\\u00a0/g, " ");
}"""


async def _composer_text(composer) -> str:
    return await composer.evaluate(COMPOSER_TEXT_JS)


async def _write_accepted(response) -> bool:
    """A 2xx response, and for LinkedIn's server-driven UI endpoints, one that reports no errors."""
    if not response.ok:
        return False
    if "/rsc-action/" not in response.url:
        return True
    try:
        body = await response.text()
    except Exception:
        return False
    return '"errors":[]' in body and '"errors":[{' not in body


async def _click_and_confirm_write(page, element, approval: ApprovedAction, url_markers: str | tuple[str, ...]) -> bool | None:
    """Click `element` and wait for LinkedIn to answer the resulting write.

    Returns True when LinkedIn accepted the write, False when the click was refused or the write was
    blocked/rejected, and None when no matching request was seen before the timeout.
    """
    markers = (url_markers,) if isinstance(url_markers, str) else url_markers
    responses: list = []
    failed: list[bool] = []

    def matches(request) -> bool:
        return request.method == "POST" and any(marker in request.url for marker in markers)

    def on_response(response) -> None:
        if matches(response.request):
            responses.append(response)

    def on_request_failed(request) -> None:
        if matches(request):
            failed.append(True)

    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
    try:
        if not await safe_click(element, approval=approval):
            return False
        for _ in range(WRITE_CONFIRM_TIMEOUT_MS // 250):
            if responses:
                return await _write_accepted(responses[0])
            if failed:
                return False
            await page.wait_for_timeout(250)
        return None
    finally:
        page.remove_listener("response", on_response)
        page.remove_listener("requestfailed", on_request_failed)


async def send_reply(page, text: str) -> bool | None:
    """Type `text` exactly and send it once. Returns True/False/None like `_click_and_confirm_write`."""
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
    return await _click_and_confirm_write(page, send_button, ApprovedAction("message", "send"), SEND_WRITE_MARKER)


async def archive_conversation(page) -> bool:
    """Archive the open conversation; True only once LinkedIn has accepted the archive request."""
    approval = ApprovedAction("message", "archive")
    archive_item = await _first_visible(page, ARCHIVE_MENU_ITEM_SELECTORS)
    if archive_item is None:
        menu = await _first_visible(page, CONVERSATION_MENU_SELECTORS)
        if menu is None or not await safe_click(menu, approval=approval):
            return False
        await page.wait_for_timeout(300)
        archive_item = await _first_visible(page, ARCHIVE_MENU_ITEM_SELECTORS)
    if archive_item is None:
        return False
    return await _click_and_confirm_write(page, archive_item, approval, ARCHIVE_WRITE_MARKER) is True


async def load_conversation(page, conversation_url: str) -> bool:
    """Open a conversation and wait until its messages have rendered; False if they never do."""
    await page.goto(conversation_url)
    await page.wait_for_load_state("load")
    try:
        await page.wait_for_selector(CONVERSATION_MESSAGE_SELECTOR, timeout=CONVERSATION_LOAD_TIMEOUT_MS)
    except PlaywrightTimeoutError:
        return False
    await page.wait_for_timeout(CONVERSATION_SETTLE_MS)
    return True


async def _archive_state_visible(page) -> bool | None:
    if await _first_visible(page, ARCHIVED_INDICATOR_SELECTORS) is not None:
        return True
    if await _first_visible(page, ARCHIVE_MENU_ITEM_SELECTORS) is not None:
        return False
    return None


async def conversation_is_archived(page) -> bool | None:
    """True/False from the thread menu's Restore/Archive option; None when the state can't be read.

    A thread opened by URL shows no archived marker of its own: only its menu says "Restore" instead of
    "Archive", so the menu is opened with a read-only click and left for the caller's next navigation.
    """
    if (state := await _archive_state_visible(page)) is not None:
        return state
    menu = await _first_visible(page, CONVERSATION_MENU_SELECTORS)
    if menu is None or not await safe_click(menu, approval=None):
        return None
    for _ in range(8):
        await page.wait_for_timeout(250)
        if (state := await _archive_state_visible(page)) is not None:
            return state
    return None


async def _find_invitation_card(page, profile_url: str):
    for card in await get_invitation_cards(page):
        invitation = await get_invitation_info(card)
        if invitation and same_profile(invitation.profile, profile_url):
            return card
    return None


async def _open_invitation_manager(page) -> None:
    await page.goto(INVITATION_MANAGER_URL)
    await page.wait_for_load_state("load")
    await page.wait_for_timeout(INVITATION_LIST_SETTLE_MS)


async def _invitation_still_pending(page, profile_url: str) -> bool | None:
    """Reload the invitation list: True if the invitation is still there, False if gone, None if the scan was incomplete."""
    await _open_invitation_manager(page)
    if await _find_invitation_card(page, profile_url) is not None:
        return True
    profiles, complete = await collect_invitation_profiles(page)
    if any(same_profile(profile, profile_url) for profile in profiles):
        return True
    if not profiles and not await page_reports_no_invitations(page):
        return None
    return False if complete else None


async def perform_invitation_action(profile_url: str, decision: Literal["accept", "ignore"]) -> ActionResult:
    approval = ApprovedAction("invitation", decision)
    try:
        async with open_linkedin(headless=True, unattended=True, approval=approval, lock_timeout=LOCK_TIMEOUT_SECONDS) as (_, page):
            await _open_invitation_manager(page)
            card = await _find_invitation_card(page, profile_url)
            if card is None:
                profiles, complete = await collect_invitation_profiles(page)
                if not any(same_profile(profile, profile_url) for profile in profiles):
                    result = ActionResult("superseded") if complete else ActionResult(None, "Couldn't find this invitation on LinkedIn; it may still be loading. Try again.")
                    logger.info("Invitation action item=%s action=%s result=%s", profile_url, decision, result.outcome or result.error)
                    return result
                card = await _find_invitation_card(page, profile_url)
            button = await _invitation_button(card, decision) if card is not None else None
            if button is None:
                return ActionResult(None, "Couldn't find the invitation's button on LinkedIn; nothing was changed. Try again.")
            # LinkedIn hides the card before its server answers, so only the server's response and a fresh
            # reload count as proof; closing the browser early silently dropped the action.
            accepted = await _click_and_confirm_write(page, button, approval, INVITATION_WRITE_MARKERS)
            pending = None if accepted is False else await _invitation_still_pending(page, profile_url)
            if accepted is False:
                result = ActionResult(None, "LinkedIn didn't accept the invitation action. Check LinkedIn before trying again.")
            elif pending is False or (pending is None and accepted is True):
                result = ActionResult("accepted" if decision == "accept" else "ignored")
            else:
                result = ActionResult(None, "Couldn't confirm the invitation action on LinkedIn. Check LinkedIn before trying again.")
            logger.info("Invitation action item=%s action=%s result=%s", profile_url, decision, result.outcome or result.error)
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
            if latest.author.strip().casefold() == logged_in_user.strip().casefold() and comparable_text(latest.content) == comparable_text(reply):
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
            # Resolve the name first: its fallback navigates away, which would unload the conversation.
            logged_in_user = await get_logged_in_user_name(page)
            if not await load_conversation(page, conversation_url):
                result = ActionResult(None, CONVERSATION_NOT_LOADED_NOTE)
                logger.info("Message action item=%s action=%s result=%s", conversation_url, action, result.error)
                return result
            messages = await extract_conversation_messages(page, "conversation participant")
            verdict, note = message_precheck(messages, logged_in_user, expected_latest, action, reply)
            latest_message = messages[-1].content if messages else None
            if verdict == "already_sent":
                result = ActionResult("sent")
            elif verdict == "stop":
                result = ActionResult(None, note, latest_message)
            elif action == "dismiss":
                result = ActionResult("archived") if await archive_conversation(page) else ActionResult(None, "Couldn't archive the conversation. Check LinkedIn before trying again.")
            else:
                sent = await send_reply(page, reply)
                if sent is True or (sent is None and await _sent_reply_is_visible(page, reply, logged_in_user)):
                    result = ActionResult("sent")
                elif sent is None:
                    result = ActionResult(None, "Couldn't confirm the message was sent. Check LinkedIn before trying again.")
                else:
                    result = ActionResult(None, "LinkedIn didn't accept the reply; nothing was sent. Check LinkedIn before trying again.")
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
