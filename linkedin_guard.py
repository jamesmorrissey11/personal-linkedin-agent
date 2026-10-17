"""Guards that make every LinkedIn write a human-approved, per-item, single-use action.

Layers implemented here (see issues #41 and #46):
1. Network kill switch: `install_linkedin_write_guard` aborts every non-GET request to a LinkedIn
   messaging endpoint on a browser context, whatever UI code or selector triggered it.
2. Guarded UI actions: `safe_click` refuses destructive-looking targets, and the composer guard
   cancels typing/Enter inside any message composer.

Scraping and sync contexts install the guard without an approval and stay fully guarded, so reading never
marks anything read. An action context opened for one item James approved in Agent Inbox passes an
`ApprovedAction`: a "message" approval lifts the composer guard and keeps the network layer default-deny,
allowing only exactly one primary write for the approved label (send or archive) per context plus an explicit
allow-list of incidental writes (read receipts, delivery acknowledgements, typing, presence). It unlocks
only the approved control in `safe_click`. The LLM agents never act; only a human approval does.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlparse

logger = logging.getLogger("linkedin_guard")

READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}
MESSAGING_PATH_PATTERN = re.compile(r"messag|messenger|conversation", re.IGNORECASE)
DESTRUCTIVE_PATTERN = re.compile(r"(?<![a-z])(send|reply|delete|archive|report|block|leave|spam|recall|unsend)(?![a-z])", re.IGNORECASE)
INTERACTIVE_TAGS = {"button", "a", "input"}
MAX_TEXT_LENGTH_CHECKED = 40
MESSAGE_APPROVAL_LABELS = {"send", "archive"}
# Confirmed against live LinkedIn traffic (2026-10-17): sending POSTs
# voyagerMessagingDashMessengerMessages?action=createMessage, and archiving POSTs
# voyagerMessagingDashMessengerConversations?action=addCategory with {"category": "ARCHIVE"} in the body
# (the same action with any other category, e.g. spam, stays blocked).
SEND_WRITE_PATTERN = re.compile(r"[?&]action=createMessage(?:&|$)", re.IGNORECASE)
ADD_CATEGORY_WRITE_PATTERN = re.compile(r"[?&]action=addCategory(?:&|$)", re.IGNORECASE)
INCIDENTAL_WRITE_PATTERN = re.compile(
    r"presenceStatuses|markAllMessagesAsSeen|sendDeliveryAcknowledgement|typing|seenReceipt|markAsSeen|markRead|markAsRead",
    re.IGNORECASE,
)

# JS run on an element to collect everything that describes what it does (never the content of message cards).
ELEMENT_DESCRIPTOR_JS = """el => {
    const attr = name => el.getAttribute(name) || "";
    const tag = el.tagName.toLowerCase();
    const interactive = ["button", "a", "input"].includes(tag) || attr("role") === "button";
    return {
        tag,
        interactive,
        ariaLabel: attr("aria-label"),
        title: attr("title"),
        name: attr("name"),
        id: el.id || "",
        type: attr("type"),
        controlName: attr("data-control-name"),
        className: typeof el.className === "string" ? el.className : "",
        text: interactive ? (el.innerText || el.value || "").trim() : "",
    };
}"""

# Capture-phase handlers cancel every keystroke, paste, and edit inside a message composer.
COMPOSER_GUARD_SCRIPT = """
(() => {
    const COMPOSER = "[contenteditable], [contenteditable='true'], .msg-form, .msg-form__contenteditable, form[class*='msg-form'] *, div[role='textbox']";
    window.__blockedComposerInput = 0;
    const block = event => {
        const target = event.target;
        if (!target || !target.closest || !target.closest(COMPOSER)) return;
        window.__blockedComposerInput += 1;
        event.preventDefault();
        event.stopImmediatePropagation();
    };
    for (const type of ["keydown", "keypress", "keyup", "beforeinput", "paste", "drop"]) {
        window.addEventListener(type, block, true);
    }
})();
"""


@dataclass(frozen=True)
class BlockedLinkedInWrite:
    """Record of one refused write attempt, surfaced in logs and run summaries."""

    layer: str
    detail: str
    timestamp: float = field(default_factory=time.time)

    def __str__(self) -> str:
        return f"[{self.layer}] {self.detail}"


@dataclass(frozen=True)
class ApprovedAction:
    """A human approval for one action on one item. For "message", `label` is "send" or "archive"."""

    scope: Literal["invitation", "message"]
    label: str

    def __post_init__(self) -> None:
        if self.scope not in ("invitation", "message"):
            raise ValueError(f"Unknown approval scope: {self.scope!r}")
        if self.scope == "message" and self.label not in MESSAGE_APPROVAL_LABELS:
            raise ValueError(f"Message approvals only cover {sorted(MESSAGE_APPROVAL_LABELS)}, not {self.label!r}")


_blocked: list[BlockedLinkedInWrite] = []


def record_blocked(layer: str, detail: str) -> BlockedLinkedInWrite:
    event = BlockedLinkedInWrite(layer, detail)
    _blocked.append(event)
    logger.warning("BLOCKED LinkedIn write %s", event)
    return event


def blocked_writes() -> list[BlockedLinkedInWrite]:
    return list(_blocked)


def reset_blocked_writes() -> None:
    _blocked.clear()


def blocked_write_summary() -> str | None:
    """One-line summary for run logs/notifications, or None when nothing was blocked."""
    if not _blocked:
        return None
    return f"{len(_blocked)} LinkedIn write attempt(s) blocked by the safety guard"


def is_messaging_url(url: str) -> bool:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host != "linkedin.com" and not host.endswith(".linkedin.com"):
        return False
    return bool(MESSAGING_PATH_PATTERN.search(f"{parsed.path}?{parsed.query}"))


def is_messaging_write(method: str, url: str) -> bool:
    """True for any non-read request to a LinkedIn messaging endpoint."""
    return method.upper() not in READ_ONLY_METHODS and is_messaging_url(url)


async def _guard_route(route) -> None:
    request = route.request
    if is_messaging_write(request.method, request.url):
        record_blocked("network", f"{request.method} {request.url}")
        await route.abort("blockedbyclient")
    else:
        await route.fallback()


def _json_body(body: str | None) -> object:
    try:
        return json.loads(body or "")
    except ValueError:
        return None


def primary_write_label(url: str, body: str | None = None) -> str | None:
    """Return "send" or "archive" when the request is that primary messaging write, else None."""
    if SEND_WRITE_PATTERN.search(url):
        return "send"
    if ADD_CATEGORY_WRITE_PATTERN.search(url):
        payload = _json_body(body)
        if isinstance(payload, dict) and payload.get("category") == "ARCHIVE":
            return "archive"
    return None


def is_incidental_write(url: str, body: str | None = None) -> bool:
    """Presence, typing, delivery acknowledgements, and read receipts: writes that never change a conversation."""
    if INCIDENTAL_WRITE_PATTERN.search(url):
        return True
    return _json_body(body) == {"patch": {"$set": {"read": True}}}


async def install_linkedin_write_guard(context, approval: ApprovedAction | None = None) -> None:
    """Install the network kill switch and composer-input guard on a Playwright browser context.

    With a "message" approval the composer guard is not installed and messaging writes stay default-deny:
    only one primary write matching the approved label, plus incidental writes (presence, delivery
    acknowledgements, typing, read receipts), may pass per context.
    """
    if approval is None or approval.scope != "message":
        await context.route(is_messaging_url, _guard_route)
        await context.add_init_script(COMPOSER_GUARD_SCRIPT)
        return

    primary_writes = 0

    async def approved_route(route) -> None:
        nonlocal primary_writes
        request = route.request
        if not is_messaging_write(request.method, request.url):
            await route.fallback()
            return
        body = request.post_data
        label = primary_write_label(request.url, body)
        if label == approval.label and primary_writes == 0:
            primary_writes += 1
            await route.fallback()
            return
        if label is None and is_incidental_write(request.url, body):
            await route.fallback()
            return
        reason = "second primary write" if label == approval.label else "unapproved write"
        record_blocked("network", f"{reason} under {approval}: {request.method} {request.url}")
        await route.abort("blockedbyclient")

    await context.route(is_messaging_url, approved_route)


def describe_destructive_match(descriptor: dict) -> str | None:
    """Return the matched token if the element descriptor looks destructive, else None."""
    fields = [descriptor.get("ariaLabel"), descriptor.get("title"), descriptor.get("name"), descriptor.get("id"), descriptor.get("controlName"), descriptor.get("className")]
    if descriptor.get("type") == "submit":
        fields.append("send (submit)")
    text = descriptor.get("text") or ""
    if descriptor.get("interactive") and len(text) <= MAX_TEXT_LENGTH_CHECKED:
        fields.append(text)
    for value in fields:
        if value and (match := DESTRUCTIVE_PATTERN.search(value.replace("-", " ").replace("_", " "))):
            return match.group(1).lower()
    return None


def approval_permits(approval: ApprovedAction | None, matched: str) -> bool:
    if approval is None:
        return False
    if approval.scope == "invitation":
        return True
    return approval.scope == "message" and approval.label in MESSAGE_APPROVAL_LABELS and matched == approval.label


async def safe_click(element, *, approval: ApprovedAction | None = None) -> bool:
    """Click `element` unless it looks like a destructive messaging control; returns False when refused."""
    descriptor = await element.evaluate(ELEMENT_DESCRIPTOR_JS)
    matched = describe_destructive_match(descriptor)
    if matched and not approval_permits(approval, matched):
        record_blocked("ui", f"refused click on '{matched}' control: {descriptor}")
        return False
    await element.click()
    return True
