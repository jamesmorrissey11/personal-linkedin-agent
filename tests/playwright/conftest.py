"""Pytest conftest for tests/playwright.

Importing tests.playwright.helpers here (before any test module imports invitations_manager or
inbox_manager) sets harmless placeholder Azure env vars so those modules can be imported without
real credentials. See helpers.py for details.
"""

import tests.playwright.helpers  # noqa: F401
