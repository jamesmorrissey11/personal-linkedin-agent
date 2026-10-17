"""Proves the LinkedIn write guard blocks mis-clicks, composer input, and messaging write requests.

A fake linkedin.com serves tests/playwright/fixtures/messaging_write_controls.html and counts every
POST to the messaging write endpoint that actually reaches the "server".
"""

import pytest
from playwright.async_api import async_playwright

import linkedin_guard
from linkedin_guard import blocked_writes, install_linkedin_write_guard, reset_blocked_writes, safe_click
from tests.async_helpers import run_async_test
from tests.playwright.helpers import FIXTURES_DIR

PAGE_URL = "https://www.linkedin.com/messaging/"
WRITE_URL = "https://www.linkedin.com/voyager/api/voyagerMessagingDashMessengerMessages?action=createMessage"
READ_URL = "https://www.linkedin.com/voyager/api/messaging/conversations"


def run_scenario(scenario, headless=True):
    async def runner():
        reset_blocked_writes()
        hits = []

        async def fake_linkedin(route):
            request = route.request
            if request.method != "GET":
                hits.append(f"{request.method} {request.url}")
                await route.fulfill(status=200, body="{}")
            elif request.url == PAGE_URL:
                await route.fulfill(path=FIXTURES_DIR / "messaging_write_controls.html")
            else:
                await route.fulfill(status=200, body="{}")

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=headless)
            context = await browser.new_context()
            await context.route("https://www.linkedin.com/**", fake_linkedin)
            await install_linkedin_write_guard(context)
            page = await context.new_page()
            await page.goto(PAGE_URL)
            try:
                return await scenario(page, hits)
            finally:
                await browser.close()

    return run_async_test(runner)


@pytest.mark.parametrize("selector", ["#send", "#delete", "#archive", "#report"])
def test_safe_click_refuses_send_and_delete_controls(selector):
    async def scenario(page, hits):
        element = await page.query_selector(selector)
        assert await safe_click(element) is False
        assert await page.evaluate("window.__sendCount") == 0
        assert hits == []
        assert len(blocked_writes()) == 1

    run_scenario(scenario)


def test_safe_click_still_clicks_harmless_controls():
    async def scenario(page, hits):
        element = await page.query_selector("li.msg-conversation-listitem")
        assert await safe_click(element) is True
        assert blocked_writes() == []

    run_scenario(scenario)


@pytest.mark.parametrize("headless", [True])
def test_raw_click_on_send_is_stopped_by_network_guard(headless):
    async def scenario(page, hits):
        await page.click("#send")
        await page.wait_for_timeout(300)
        assert await page.evaluate("window.__writeAttempts") == 1
        assert await page.evaluate("window.__writeFailures") == 1
        assert hits == []
        assert any(event.layer == "network" for event in blocked_writes())
        assert "blocked" in linkedin_guard.blocked_write_summary()

    run_scenario(scenario, headless=headless)


@pytest.mark.parametrize("method", ["POST", "PUT", "DELETE", "PATCH"])
def test_non_get_messaging_requests_are_aborted(method):
    async def scenario(page, hits):
        failed = await page.evaluate(f"fetch('{WRITE_URL}', {{method: '{method}'}}).then(() => false, () => true)")
        assert failed is True
        assert hits == []
        assert blocked_writes()

    run_scenario(scenario)


def test_get_messaging_requests_are_allowed():
    async def scenario(page, hits):
        status = await page.evaluate(f"fetch('{READ_URL}').then(r => r.status)")
        assert status == 200
        assert blocked_writes() == []

    run_scenario(scenario)


def test_composer_typing_and_enter_are_refused():
    async def scenario(page, hits):
        await page.click("#composer")
        await page.keyboard.type("hello there")
        await page.keyboard.press("Enter")
        assert (await page.inner_text("#composer")).strip() == ""
        assert await page.evaluate("window.__blockedComposerInput") > 0
        assert hits == []

    run_scenario(scenario)


def test_composer_fill_is_refused():
    async def scenario(page, hits):
        try:
            await page.fill("#composer", "hello there")
        except Exception:
            pass
        assert (await page.inner_text("#composer")).strip() == ""

    run_scenario(scenario)
