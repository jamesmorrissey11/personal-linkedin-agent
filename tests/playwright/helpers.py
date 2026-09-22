"""Shared helpers for Playwright-based scraping tests.

These tests never launch a credentialed LinkedIn session or touch
``playwright/.auth/state.json``. Pages are populated from static HTML fixtures under
``tests/playwright/fixtures/`` via ``file://`` URLs, so the suite is deterministic and
safe to run in CI.
"""

from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Azure env var placeholders needed to import invitations_manager.py / inbox_manager.py are set
# in the top-level tests/conftest.py (shared with tests/unit).


def fixture_url(name: str) -> str:
    """Return a file:// URL for a fixture HTML file, for use with page.goto()."""
    return (FIXTURES_DIR / name).resolve().as_uri()
