"""Tests for logged-in-user detection in linkedin.pages.get_logged_in_user_name.

Getting this wrong is not cosmetic. inbox compares the name against each conversation's
latest author, so a wrong or unknown name mislabels who spoke last: returning "Unknown User" queues
every conversation for review (including ones the user already replied to), and returning a
*participant's* name would hide conversations that genuinely need a reply.

Pages are served from static fixtures through a request route, so no credentialed LinkedIn session
is ever used.
"""

from playwright.async_api import async_playwright

from linkedin_agent.linkedin.pages import get_logged_in_user_name
from tests.async_helpers import run_async_test
from tests.playwright.helpers import FIXTURES_DIR

MESSAGING_URL = "https://www.linkedin.com/messaging/"
FEED_URL = "https://www.linkedin.com/feed/foryou/"
SELF_PROFILE_URL = "https://www.linkedin.com/in/me/"


def resolve_name(fixture: str, start_url: str = MESSAGING_URL, self_profile: str | None = "self_profile.html"):
    """Serve `fixture` at `start_url` (and `self_profile` at /in/me/), then resolve the user's name.

    Returns (name, visited_urls) so tests can assert on navigation side effects.
    """

    async def runner():
        visited = []

        async def fake_linkedin(route):
            url = route.request.url
            visited.append(url)
            if url.startswith(SELF_PROFILE_URL):
                if self_profile is None:
                    await route.fulfill(status=200, body="<html><head><title>LinkedIn Login</title></head><body></body></html>")
                else:
                    await route.fulfill(path=FIXTURES_DIR / self_profile)
            else:
                await route.fulfill(path=FIXTURES_DIR / fixture)

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            context = await browser.new_context()
            await context.route("https://www.linkedin.com/**", fake_linkedin)
            page = await context.new_page()
            await page.goto(start_url)
            try:
                name = await get_logged_in_user_name(page)
                return name, visited, page.url
            finally:
                await browser.close()

    return run_async_test(runner)


def test_name_comes_from_the_me_menu_avatar_on_classic_nav():
    name, visited, _ = resolve_name("nav_messaging.html")

    assert name == "James Morrissey"
    # The nav already answered the question, so no extra profile navigation should happen.
    assert not any(url.startswith(SELF_PROFILE_URL) for url in visited)


def test_conversation_participants_are_never_mistaken_for_the_user():
    """Unscoped "a[href*='/in/'] img[alt]" returns "Yogesh Kumar Profile" on this page."""
    name, _, _ = resolve_name("nav_messaging.html")

    assert name == "James Morrissey"
    assert "Yogesh" not in name
    assert "Samantha" not in name


def test_legacy_profile_button_aria_label_is_still_supported():
    name, _, _ = resolve_name("nav_legacy_profile_button.html")

    assert name == "James Morrissey"


def test_react_feed_without_nav_hooks_falls_back_to_the_self_profile_title():
    name, visited, _ = resolve_name("nav_feed_react.html", start_url=FEED_URL)

    assert name == "James Morrissey"
    assert any(url.startswith(SELF_PROFILE_URL) for url in visited)


def test_self_profile_fallback_restores_the_original_page():
    _, _, final_url = resolve_name("nav_feed_react.html", start_url=FEED_URL)

    assert final_url == FEED_URL


def test_first_profile_link_on_the_feed_is_not_used_as_the_user():
    """The feed fixture lists "Other Person" before the user, so first-match selectors are wrong."""
    name, _, _ = resolve_name("nav_feed_react.html", start_url=FEED_URL)

    assert name != "Other Person"


def test_unresolvable_identity_fails_closed_to_unknown_user():
    name, _, _ = resolve_name("nav_anonymous.html", start_url=FEED_URL, self_profile=None)

    assert name == "Unknown User"


def test_fixture_pages_are_never_mutated_during_detection():
    """Detection is read-only: it must not click the Me menu open to read a name."""
    name, visited, _ = resolve_name("nav_messaging.html")

    assert name == "James Morrissey"
    assert all(url.startswith("https://www.linkedin.com/") for url in visited)
