"""Shared helpers for Playwright-based scraping tests.

These tests never launch a credentialed LinkedIn session or touch
``playwright/.auth/state.json``. Pages are populated from static HTML fixtures under
``tests/playwright/fixtures/`` via ``file://`` URLs, so the suite is deterministic and
safe to run in CI.
"""

import os
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# invitations_manager.py / inbox_manager.py read these env vars at import time to build an Azure
# OpenAI client (no network call happens until the agent actually runs). Set harmless placeholders
# so importing the modules for their scraping selectors/constants works without real Azure
# credentials, keeping this suite safe to run in CI.
os.environ.setdefault("AZURE_TENANT_ID", "test-tenant-id")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example-test.openai.azure.com")
os.environ.setdefault("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-deployment")


def fixture_url(name: str) -> str:
    """Return a file:// URL for a fixture HTML file, for use with page.goto()."""
    return (FIXTURES_DIR / name).resolve().as_uri()
