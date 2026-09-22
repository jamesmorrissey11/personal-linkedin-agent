"""Top-level pytest conftest, shared by tests/playwright and tests/unit.

Sets harmless placeholder Azure env vars before any test module imports
invitations_manager or inbox_manager, since those modules build an Azure OpenAI client
at import time (no network call happens until an agent is actually run).
"""

import os

os.environ.setdefault("AZURE_TENANT_ID", "test-tenant-id")
os.environ.setdefault("AZURE_OPENAI_ENDPOINT", "https://example-test.openai.azure.com")
os.environ.setdefault("AZURE_OPENAI_CHAT_DEPLOYMENT", "test-deployment")

# Note: async production functions (execute_action, get_profile_info,
# ignore_newsletter_invitations, run_and_log_agent, rank_messages_for_reply) are
# exercised via plain asyncio.run() inside sync test functions, using Playwright's
# async_api directly, rather than pytest.mark.anyio/async def tests - pytest-playwright
# only ships sync fixtures, and adding pytest-asyncio purely to run async tests would be
# a dependency not required for mocking. See docs/delegations/test-backfill.md and the
# PR description for details.


def pytest_collection_modifyitems(items):
    """Run pytest-playwright's sync `page`-fixture tests after asyncio.run() tests.

    Playwright does not support mixing its sync and async APIs within the same process:
    once pytest-playwright's sync `page` fixture has been used, a later
    async_playwright() + asyncio.run() call in the same thread fails with
    "asyncio.run() cannot be called from a running event loop". Running the
    asyncio.run()-based tests first (order is otherwise alphabetical-by-file) avoids
    that conflict without needing pytest-asyncio or pytest-xdist.
    """
    items.sort(key=lambda item: "page" in item.fixturenames)
