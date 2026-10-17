"""Tests for the invitation-card scraping selectors used by invitations_manager.py.

Loads a static fixture (tests/playwright/fixtures/invitation_manager.html) instead of a live
LinkedIn session, and exercises the same selector strings the production code uses.
"""

from playwright.async_api import async_playwright
from playwright.sync_api import Page

from invitations_manager import INVITATION_CARD_SELECTORS
from linkedin_actions import click_invitation_button
from tests.async_helpers import run_async_test
from tests.playwright.helpers import fixture_url


def test_invitation_card_selectors_find_all_cards(page: Page):
    page.goto(fixture_url("invitation_manager.html"))

    cards = []
    for selector in INVITATION_CARD_SELECTORS:
        found = page.query_selector_all(selector)
        if found:
            cards = found
            break

    assert len(cards) == 2


def test_accept_and_ignore_buttons_are_scoped_to_card(page: Page):
    page.goto(fixture_url("invitation_manager.html"))

    card = page.query_selector_all(INVITATION_CARD_SELECTORS[0])[0]
    accept_button = card.query_selector("button[aria-label*='Accept']")
    ignore_button = card.query_selector("button[aria-label*='Ignore']")

    assert accept_button is not None
    accept_label = accept_button.get_attribute("aria-label")
    assert accept_label is not None
    assert "Jane Doe" in accept_label
    assert ignore_button is not None
    ignore_label = ignore_button.get_attribute("aria-label")
    assert ignore_label is not None
    assert "Jane Doe" in ignore_label


def test_newsletter_ignore_button_is_found_by_selector(page: Page):
    page.goto(fixture_url("invitation_manager.html"))

    ignore_button = page.query_selector("button[aria-label^='Ignore invitation for ']")

    assert ignore_button is not None
    assert ignore_button.get_attribute("aria-label") == "Ignore invitation for Weekly Newsletter"


def test_only_human_approved_invitation_action_mutates_intended_card():
    async def scenario():
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch()
            page = await browser.new_page()
            await page.goto(fixture_url("invitation_manager.html"))
            await page.evaluate(
                """
                window.__invitationActions = [];
                document.querySelectorAll("button").forEach((button) => {
                  button.addEventListener("click", () => window.__invitationActions.push(button.getAttribute("aria-label")));
                });
                """
            )

            cards = await page.query_selector_all(INVITATION_CARD_SELECTORS[0])
            assert await page.evaluate("window.__invitationActions") == []

            assert await click_invitation_button(cards[0], "accept") is True

            assert await page.evaluate("window.__invitationActions") == ["Accept Jane Doe's invitation to connect"]
            assert await page.query_selector("button[aria-label='Ignore invitation for Weekly Newsletter']") is not None
            await browser.close()

    run_async_test(scenario)
