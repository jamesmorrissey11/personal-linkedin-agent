"""Guards that make "no LinkedIn message is sent or deleted without explicit human approval" an invariant.

Layers implemented here (see issue #41):
1. Network kill switch: `install_linkedin_write_guard` aborts every non-GET request to a LinkedIn
   messaging endpoint on a browser context, whatever UI code or selector triggered it.
2. Guarded UI actions: `safe_click` refuses destructive-looking targets, and the composer guard
   cancels typing/Enter inside any message composer.

No message-sending capability exists. If one is ever added, approval must be per message, bound to the
conversation URL and the SHA-256 of the exact final text shown to the human, single use, short-lived,
and only valid in an interactive session. Any mismatch fails closed. `ApprovedAction` never authorizes
the "message" scope today.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlparse

logger = logging.getLogger("linkedin_guard")

READ_ONLY_METHODS = {"GET", "HEAD", "OPTIONS"}
MESSAGING_PATH_PATTERN = re.compile(r"messag|messenger|conversation", re.IGNORECASE)
DESTRUCTIVE_PATTERN = re.compile(r"(?<![a-z])(send|reply|delete|archive|report|block|leave|spam|recall|unsend)(?![a-z])", re.IGNORECASE)
INTERACTIVE_TAGS = {"button", "a", "input"}
MAX_TEXT_LENGTH_CHECKED = 40

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


@dataclass
class ApprovedAction:
    """A human approval for a guarded UI action. Message writes are never authorizable."""

    scope: str  # only "invitation" is honored
    label: str


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


async def install_linkedin_write_guard(context) -> None:
    """Install the network kill switch and composer-input guard on a Playwright browser context."""
    await context.route(is_messaging_url, _guard_route)
    await context.add_init_script(COMPOSER_GUARD_SCRIPT)


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


def approval_permits(approval: ApprovedAction | None) -> bool:
    return approval is not None and approval.scope == "invitation"


async def safe_click(element, *, approval: ApprovedAction | None = None) -> bool:
    """Click `element` unless it looks like a destructive messaging control; returns False when refused."""
    descriptor = await element.evaluate(ELEMENT_DESCRIPTOR_JS)
    matched = describe_destructive_match(descriptor)
    if matched and not approval_permits(approval):
        record_blocked("ui", f"refused click on '{matched}' control: {descriptor}")
        return False
    await element.click()
    return True
