"""Tests for invitations_manager.py's get_profile_info() fallback text-extraction path.

Loads static profile-page fixtures via file:// URLs (never a live LinkedIn session) to
cover: successful extraction, an empty <main> element, and a page where the
`main, div[role='main']` selector never matches (simulating a page that didn't finish
loading). The last case monkeypatches PROFILE_CONTENT_TIMEOUT_MS down to keep the test
fast; this only patches the module attribute for the duration of the test and does not
change production code.

Tests are plain (sync) functions driving an async helper via `asyncio.run()` since
get_profile_info() is async; see tests/conftest.py for why pytest-playwright's sync
`page`-fixture tests are reordered to run after these.
"""

import asyncio

from playwright.async_api import async_playwright

import invitations_manager
from invitations_manager import get_profile_info
from tests.playwright.helpers import fixture_url


async def _get_profile_info(fixture_name: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        # get_profile_info() opens a second page via `page.context.new_page()`, which
        # Playwright rejects on a context created via the browser.new_page() shorthand
        # (it owns a single page). Use an explicit context instead.
        context = await browser.new_context()
        page = await context.new_page()
        try:
            return await get_profile_info(page, fixture_url(fixture_name))
        finally:
            await browser.close()


def test_get_profile_info_extracts_main_content():
    profile_text = asyncio.run(_get_profile_info("profile_page.html"))

    assert "Senior Software Engineer at Contoso" in profile_text


def test_get_profile_info_reports_empty_main_content():
    profile_text = asyncio.run(_get_profile_info("profile_page_empty.html"))

    assert profile_text == "Profile information not available because the profile page content was empty."


def test_get_profile_info_reports_timeout_when_main_never_appears(monkeypatch):
    monkeypatch.setattr(invitations_manager, "PROFILE_CONTENT_TIMEOUT_MS", 500)

    profile_text = asyncio.run(_get_profile_info("profile_page_no_main.html"))

    assert profile_text == "Profile information not available because LinkedIn did not finish loading the profile page."
