from playwright.async_api import async_playwright

from linkedin_actions import ARCHIVE_MENU_ITEM_SELECTORS, ARCHIVED_INDICATOR_SELECTORS, COMPOSER_SELECTORS, CONVERSATION_MENU_SELECTORS, SEND_BUTTON_SELECTORS
from tests.async_helpers import run_async_test
from tests.playwright.helpers import FIXTURES_DIR

PAGE_URL = "https://www.linkedin.com/messaging/thread/fixture/"


def load_fixture(name, scenario):
    async def runner():
        async def fake_linkedin(route):
            await route.fulfill(path=FIXTURES_DIR / name)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.route("https://www.linkedin.com/**", fake_linkedin)
            page = await context.new_page()
            await page.goto(PAGE_URL)
            try:
                return await scenario(page)
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
    async def scenario(page):
        await assert_fallback_matches(page, COMPOSER_SELECTORS)
        await assert_fallback_matches(page, SEND_BUTTON_SELECTORS)
        await assert_fallback_matches(page, CONVERSATION_MENU_SELECTORS)
        await assert_fallback_matches(page, ARCHIVE_MENU_ITEM_SELECTORS)

    load_fixture("conversation_thread.html", scenario)


def test_archived_indicator_selectors_match_only_archived_fixture():
    async def archived(page):
        await assert_fallback_matches(page, ARCHIVED_INDICATOR_SELECTORS)

    async def ordinary(page):
        counts = [await page.locator(selector).count() for selector in ARCHIVED_INDICATOR_SELECTORS]
        assert not any(counts)

    load_fixture("conversation_archived.html", archived)
    load_fixture("conversation_thread.html", ordinary)
