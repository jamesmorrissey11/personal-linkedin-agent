from playwright.async_api import async_playwright

from linkedin_actions import ARCHIVE_MENU_ITEM_SELECTORS, ARCHIVED_INDICATOR_SELECTORS, COMPOSER_SELECTORS, CONVERSATION_MENU_SELECTORS, SEND_BUTTON_SELECTORS, archive_conversation, conversation_is_archived, send_reply
from linkedin_guard import ApprovedAction, install_linkedin_write_guard
from tests.async_helpers import run_async_test
from tests.playwright.helpers import FIXTURES_DIR

PAGE_URL = "https://www.linkedin.com/messaging/thread/fixture/"
SEND_URL = "https://www.linkedin.com/voyager/api/voyagerMessagingDashMessengerMessages?action=createMessage"
ARCHIVE_URL = "https://www.linkedin.com/voyager/api/voyagerMessagingGraphQL/graphql?action=archive"


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
            """(element, url) => element.addEventListener("click", event => {
                event.preventDefault();
                fetch(url, {method: "POST", body: "{}"});
            })""",
            ARCHIVE_URL,
        )

        assert await archive_conversation(page) is True
        await page.wait_for_timeout(100)
        assert hits == [f"POST {ARCHIVE_URL}"]

    load_fixture("conversation_thread.html", scenario, ApprovedAction("message", "archive"))


def test_conversation_is_archived_detects_both_fixtures():
    async def archived(page, _hits):
        assert await conversation_is_archived(page) is True

    async def ordinary(page, _hits):
        assert await conversation_is_archived(page) is False

    load_fixture("conversation_archived.html", archived)
    load_fixture("conversation_thread.html", ordinary)
