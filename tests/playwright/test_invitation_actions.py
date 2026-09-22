"""Tests for the accept/ignore click flow and newsletter auto-ignore loop in
invitations_manager.py.

These exercise the real async `execute_action` / `ignore_newsletter_invitations`
functions against a headless Chromium page loaded from a static HTML fixture (never a
live LinkedIn session). Each test is a plain (sync) function that drives an async helper via `asyncio.run()`,
rather than an `async def` test with pytest-asyncio/anyio, to avoid adding a
dependency not required for mocking. Playwright does not support mixing its sync and
async APIs in the same process, so tests/conftest.py reorders these asyncio.run()-based
tests to run before pytest-playwright's sync `page`-fixture tests in the same session.
"""

import asyncio

from playwright.async_api import async_playwright

from invitations_manager import InvitationAction, InvitationDecision, execute_action, ignore_newsletter_invitations
from tests.playwright.helpers import fixture_url


async def _with_page(fixture_name: str, run):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        try:
            await page.goto(fixture_url(fixture_name))
            return await run(page)
        finally:
            await browser.close()


def test_execute_action_clicks_accept_button():
    async def run(page):
        card = await page.query_selector("#card-both")
        decision = InvitationDecision(action=InvitationAction.ACCEPT, reason="technical role")
        result = await execute_action(page, card, decision)
        accept_button = await card.query_selector("button[aria-label*='Accept']")
        return result, await accept_button.get_attribute("data-clicked")

    result, clicked = asyncio.run(_with_page("invitation_manager_interactive.html", run))

    assert clicked == "true"
    assert result.action == InvitationAction.ACCEPT


def test_execute_action_clicks_ignore_button():
    async def run(page):
        card = await page.query_selector("#card-both")
        decision = InvitationDecision(action=InvitationAction.IGNORE, reason="recruiter")
        result = await execute_action(page, card, decision)
        ignore_button = await card.query_selector("button[aria-label*='Ignore']")
        return result, await ignore_button.get_attribute("data-clicked")

    result, clicked = asyncio.run(_with_page("invitation_manager_interactive.html", run))

    assert clicked == "true"
    assert result.action == InvitationAction.IGNORE


def test_execute_action_falls_back_to_undecided_when_button_missing():
    async def run(page):
        card = await page.query_selector("#card-accept-only")
        decision = InvitationDecision(action=InvitationAction.IGNORE, reason="recruiter")
        return await execute_action(page, card, decision)

    result = asyncio.run(_with_page("invitation_manager_interactive.html", run))

    assert result.action == InvitationAction.UNDECIDED


def test_ignore_newsletter_invitations_clicks_all_and_counts_them():
    async def run(page):
        count = await ignore_newsletter_invitations(page)
        remaining = await page.query_selector_all("button[aria-label^='Ignore invitation for ']")
        return count, remaining

    ignored_count, remaining = asyncio.run(_with_page("newsletter_invitations.html", run))

    assert ignored_count == 2
    assert remaining == []
