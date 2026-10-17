import json
from contextlib import asynccontextmanager

import pytest
from playwright.async_api import async_playwright

import linkedin_actions
from linkedin_actions import ARCHIVE_MENU_ITEM_SELECTORS, ARCHIVED_INDICATOR_SELECTORS, COMPOSER_SELECTORS, CONVERSATION_MENU_SELECTORS, SEND_BUTTON_SELECTORS, _composer_text, archive_conversation, conversation_is_archived, send_reply
from linkedin_guard import ApprovedAction, install_linkedin_write_guard
from tests.async_helpers import run_async_test
from tests.playwright.helpers import FIXTURES_DIR

PAGE_URL = "https://www.linkedin.com/messaging/thread/fixture/"
SEND_URL = "https://www.linkedin.com/voyager/api/voyagerMessagingDashMessengerMessages?action=createMessage"
ARCHIVE_URL = "https://www.linkedin.com/voyager/api/voyagerMessagingDashMessengerConversations?action=addCategory"
ARCHIVE_BODY = '{"conversationUrns":["urn:li:msg_conversation:(urn:li:fsd_profile:abc,2-xyz)"],"category":"ARCHIVE"}'


def load_fixture(name, scenario, approval=None):
    async def runner():
        hits = []

        async def fake_linkedin(route):
            request = route.request
            if request.method != "GET":
                hits.append(f"{request.method} {request.url}")
                await route.fulfill(status=200, body="{}")
            elif request.url == PAGE_URL:
                await route.fulfill(path=FIXTURES_DIR / name)
            else:
                await route.fulfill(status=200, body="{}")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.route("https://www.linkedin.com/**", fake_linkedin)
            await install_linkedin_write_guard(context, approval)
            page = await context.new_page()
            await page.goto(PAGE_URL)
            try:
                return await scenario(page, hits)
            finally:
                await browser.close()

    return run_async_test(runner)


def assert_fallback_matches(page, selectors):
    async def check():
        assert len(selectors) >= 2
        counts = [await page.locator(selector).count() for selector in selectors]
        assert any(counts)

    return check()


def test_live_action_selectors_match_conversation_fixture():
    async def scenario(page, _hits):
        await assert_fallback_matches(page, COMPOSER_SELECTORS)
        await assert_fallback_matches(page, SEND_BUTTON_SELECTORS)
        await assert_fallback_matches(page, CONVERSATION_MENU_SELECTORS)
        await assert_fallback_matches(page, ARCHIVE_MENU_ITEM_SELECTORS)

    load_fixture("conversation_thread.html", scenario)


def test_archived_indicator_selectors_match_only_archived_fixture():
    async def archived(page, _hits):
        await assert_fallback_matches(page, ARCHIVED_INDICATOR_SELECTORS)

    async def ordinary(page, _hits):
        counts = [await page.locator(selector).count() for selector in ARCHIVED_INDICATOR_SELECTORS]
        assert not any(counts)

    load_fixture("conversation_archived.html", archived)
    load_fixture("conversation_thread.html", ordinary)


def test_send_reply_types_exact_text_and_sends_once():
    text = "Thanks!\nSee you Friday 🙂"

    async def scenario(page, hits):
        send_button = page.locator(SEND_BUTTON_SELECTORS[0]).first
        await send_button.evaluate(
            """(button, url) => {
                button.disabled = false;
                button.addEventListener("click", event => {
                    event.preventDefault();
                    fetch(url, {method: "POST", body: "{}"});
                });
            }""",
            SEND_URL,
        )

        assert await send_reply(page, text) is True
        await page.wait_for_timeout(100)
        lines = await page.locator(f"{COMPOSER_SELECTORS[0]} > p").all_inner_texts()
        assert lines == ["Thanks!", "See you Friday 🙂"]
        assert hits == [f"POST {SEND_URL}"]

    load_fixture("conversation_thread.html", scenario, ApprovedAction("message", "send"))


def test_send_reply_refuses_when_composer_differs():
    text = "Thanks 🙂"

    async def scenario(page, hits):
        composer = page.locator(COMPOSER_SELECTORS[0]).first
        await composer.evaluate(
            """element => element.addEventListener("input", () => {
                element.innerText = element.innerText.replace("🙂", "");
            })"""
        )
        await page.locator(SEND_BUTTON_SELECTORS[0]).first.evaluate("(button) => button.disabled = false")

        assert await send_reply(page, text) is False
        assert (await composer.inner_text()).strip() == ""
        assert hits == []

    load_fixture("conversation_thread.html", scenario, ApprovedAction("message", "send"))


def test_archive_conversation_clicks_archive_only():
    async def scenario(page, hits):
        archive = page.locator(ARCHIVE_MENU_ITEM_SELECTORS[0]).first
        await archive.evaluate(
            """(element, [url, body]) => element.addEventListener("click", event => {
                event.preventDefault();
                fetch(url, {method: "POST", body});
            })""",
            [ARCHIVE_URL, ARCHIVE_BODY],
        )

        assert await archive_conversation(page) is True
        await page.wait_for_timeout(100)
        assert hits == [f"POST {ARCHIVE_URL}"]

    load_fixture("conversation_thread.html", scenario, ApprovedAction("message", "archive"))


def test_archive_conversation_reports_failure_when_linkedin_never_gets_the_write():
    async def scenario(page, hits):
        archive = page.locator(ARCHIVE_MENU_ITEM_SELECTORS[0]).first
        await archive.evaluate(
            """(element, [url, body]) => element.addEventListener("click", event => {
                event.preventDefault();
                fetch(url, {method: "POST", body}).catch(() => {});
            })""",
            [ARCHIVE_URL, ARCHIVE_BODY],
        )

        # A send-only context blocks the archive request, so the click alone must not count as success.
        assert await archive_conversation(page) is False
        assert hits == []

    load_fixture("conversation_thread.html", scenario, ApprovedAction("message", "send"))


@pytest.mark.parametrize(
    ("html", "expected"),
    [
        ("<p>Hi Kyle,</p><p><br></p><p>Thanks!</p><p>Line three&nbsp;&nbsp;</p><p><br></p><p>Best,</p><p>James</p>", "Hi Kyle,\n\nThanks!\nLine three  \n\nBest,\nJames"),
        ("<p>One line</p>", "One line"),
        ("first<br>second<br><br>fourth", "first\nsecond\n\nfourth"),
    ],
)
def test_composer_text_reads_linkedin_paragraph_markup(html, expected):
    async def scenario(page, _hits):
        composer = page.locator(COMPOSER_SELECTORS[0]).first
        await composer.evaluate("(element, html) => { element.innerHTML = html; }", html)
        assert await _composer_text(composer) == expected

    load_fixture("conversation_thread.html", scenario)


# A minimal SPA-like conversation: messages render only after a delay, like LinkedIn's.
DELAYED_CONVERSATION_HTML = """<!doctype html><html><body><main>
<ul id="list"></ul>
<div class="msg-form__contenteditable" contenteditable="true" role="textbox" aria-label="Write a message…"></div>
<button class="msg-form__send-button" type="submit">Send</button>
<div class="scaffold-layout__detail"><button class="msg-thread-actions__control artdeco-button--2" type="button">Options</button></div>
<div id="menu" hidden><div class="msg-thread-actions__dropdown-option" role="button">Archive</div></div>
<script>
const LATEST = __LATEST__;
setTimeout(() => {
    document.getElementById("list").innerHTML = `<li class="msg-s-message-list__event">
        <span class="msg-s-message-group__name">Grace Hopper</span>
        <p class="msg-s-event-listitem__body"></p></li>`;
    document.querySelector(".msg-s-event-listitem__body").innerText = LATEST;
}, 800);
document.querySelector(".msg-thread-actions__control").addEventListener("click", () => { document.getElementById("menu").hidden = false; });
document.querySelector(".msg-thread-actions__dropdown-option").addEventListener("click", () => {
    fetch(__ARCHIVE_URL__, {method: "POST", body: __ARCHIVE_BODY__});
});
document.querySelector(".msg-form__send-button").addEventListener("click", event => {
    event.preventDefault();
    fetch(__SEND_URL__, {method: "POST", body: JSON.stringify({text: document.querySelector(".msg-form__contenteditable").innerText})});
});
</script></main></body></html>"""


def run_message_action(monkeypatch, action, reply, expected_latest, latest_on_page):
    html = DELAYED_CONVERSATION_HTML.replace("__LATEST__", json.dumps(latest_on_page)).replace("__ARCHIVE_URL__", json.dumps(ARCHIVE_URL)).replace("__ARCHIVE_BODY__", json.dumps(ARCHIVE_BODY)).replace("__SEND_URL__", json.dumps(SEND_URL))
    hits = []

    @asynccontextmanager
    async def fake_open_linkedin(headless, unattended, approval=None, lock_timeout=0):
        async def fake_linkedin(route):
            request = route.request
            if request.method != "GET":
                hits.append(f"{request.method} {request.url}")
                await route.fulfill(status=200, body="{}")
            elif request.url == PAGE_URL:
                await route.fulfill(status=200, content_type="text/html", body=html)
            else:
                await route.fulfill(status=200, body="{}")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                await context.route("https://www.linkedin.com/**", fake_linkedin)
                await install_linkedin_write_guard(context, approval)
                yield context, await context.new_page()
            finally:
                await browser.close()

    async def fake_user_name(_page):
        return "James Morrissey"

    monkeypatch.setattr(linkedin_actions, "open_linkedin", fake_open_linkedin)
    monkeypatch.setattr(linkedin_actions, "get_logged_in_user_name", fake_user_name)
    monkeypatch.setattr(linkedin_actions, "WRITE_CONFIRM_TIMEOUT_MS", 2000)
    result = run_async_test(lambda: linkedin_actions.perform_message_action(PAGE_URL, action, reply, expected_latest))
    return result, hits


QUEUED = "Hi James,\n\nAre you open to a role?\n \n Thanks,\n Grace"


def test_dismiss_waits_for_the_conversation_then_archives(monkeypatch):
    result, hits = run_message_action(monkeypatch, "dismiss", "", QUEUED, QUEUED)

    assert (result.outcome, result.error) == ("archived", None)
    assert hits == [f"POST {ARCHIVE_URL}"]


def test_reply_waits_for_the_conversation_then_sends_multiline_text_once(monkeypatch):
    reply = "Hi Grace,\n\nThanks, but I'm only looking at MLE roles.\n\nBest,\nJames"

    result, hits = run_message_action(monkeypatch, "reply", reply, QUEUED, QUEUED)

    assert (result.outcome, result.error) == ("sent", None)
    assert hits == [f"POST {SEND_URL}"]


def test_new_incoming_message_stops_the_action(monkeypatch):
    result, hits = run_message_action(monkeypatch, "dismiss", "", QUEUED, "Following up on my last note")

    assert result.outcome is None
    assert result.error == linkedin_actions.NEW_MESSAGE_NOTE
    assert hits == []


def test_conversation_that_never_loads_reports_a_retryable_note(monkeypatch):
    monkeypatch.setattr(linkedin_actions, "CONVERSATION_LOAD_TIMEOUT_MS", 300)

    result, hits = run_message_action(monkeypatch, "dismiss", "", QUEUED, QUEUED)

    assert result.outcome is None
    assert result.error == linkedin_actions.CONVERSATION_NOT_LOADED_NOTE
    assert hits == []


def test_conversation_is_archived_detects_both_fixtures():
    async def archived(page, _hits):
        assert await conversation_is_archived(page) is True

    async def ordinary(page, _hits):
        assert await conversation_is_archived(page) is False

    load_fixture("conversation_archived.html", archived)
    load_fixture("conversation_thread.html", ordinary)


# Live LinkedIn: a thread opened by URL only reveals Restore/Archive once its menu is opened.
HIDDEN_MENU_HTML = """<!doctype html><html><body><main><div class="scaffold-layout__detail">
<button class="msg-thread-actions__control artdeco-button--2" type="button">Options</button>
<div id="menu" hidden><div class="msg-thread-actions__dropdown-option" data-view-name="message-toolbar-dropdown-toggle-archive" role="button">__LABEL__</div></div>
</div><script>
document.querySelector(".msg-thread-actions__control").addEventListener("click", () => { document.getElementById("menu").hidden = false; });
</script></main></body></html>"""


@pytest.mark.parametrize(("label", "expected"), [("Restore", True), ("Archive", False), ("Mute", None)])
def test_conversation_is_archived_opens_the_thread_menu(label, expected):
    async def runner():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context()
                await install_linkedin_write_guard(context)
                page = await context.new_page()
                await page.set_content(HIDDEN_MENU_HTML.replace("__LABEL__", label))
                return await conversation_is_archived(page)
            finally:
                await browser.close()

    assert run_async_test(runner) is expected
