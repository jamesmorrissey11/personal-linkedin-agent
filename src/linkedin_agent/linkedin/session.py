"""The serialized, guarded LinkedIn browser session: login detection, the cross-process lock, and the write guard.

Importable without the LLM stack (no pydantic_ai, openai, or azure) so the review graphs can drive LinkedIn.
"""

import asyncio
import fcntl
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from playwright.async_api import async_playwright

from linkedin_agent.linkedin.guard import ApprovedAction, blocked_write_summary, install_linkedin_write_guard
from linkedin_agent.runtime import LoginRequiredError

logger = logging.getLogger("linkedin_session")
logger.setLevel(logging.INFO)

LOCK_PATH = Path("playwright/.auth/linkedin.lock")


class LinkedInBusyError(RuntimeError):
    """Another process holds the LinkedIn session lock."""


AUTH_STATE_PATH = Path("playwright/.auth/state.json")


def _acquire_flock(handle) -> bool:
    """Try once to take the exclusive lock; False means another holder has it."""
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False


@asynccontextmanager
async def linkedin_lock(timeout_seconds: float, path: Path = LOCK_PATH):
    """Hold an exclusive flock on `path`, polling once per second; raise LinkedInBusyError on timeout.

    Every filesystem call runs in a worker thread. `langgraph dev` guards the graphs with blockbuster,
    which turns a blocking call on the event loop into a BlockingError that aborts the action, and the
    lock is held for the whole LinkedIn session, so blocking here would also stall the server.
    """
    await asyncio.to_thread(path.parent.mkdir, parents=True, exist_ok=True)
    # flock is per open file description, so each entry opens its own handle.
    handle = await asyncio.to_thread(path.open, "a")
    try:
        deadline = time.monotonic() + timeout_seconds
        while not await asyncio.to_thread(_acquire_flock, handle):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LinkedInBusyError(f"LinkedIn is busy: could not acquire {path} within {timeout_seconds:g}s.") from None
            await asyncio.sleep(min(1.0, remaining))
        try:
            yield
        finally:
            await asyncio.to_thread(fcntl.flock, handle.fileno(), fcntl.LOCK_UN)
    finally:
        await asyncio.to_thread(handle.close)


def _ensure_auth_state_sync(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("{}")


async def ensure_auth_state(path: Path = AUTH_STATE_PATH) -> None:
    """Create an empty storage-state file when none exists, without blocking the event loop."""
    await asyncio.to_thread(_ensure_auth_state_sync, path)


@asynccontextmanager
async def open_linkedin(headless: bool, unattended: bool, approval: ApprovedAction | None = None, lock_timeout: float = 3600):
    """Yield (context, page) for a logged-in LinkedIn session, holding the LinkedIn lock throughout.

    When unattended (or headless) an expired session raises LoginRequiredError instead of waiting for a human.
    """
    async with linkedin_lock(lock_timeout):
        await ensure_auth_state()

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=headless)
            try:
                context = await browser.new_context(storage_state=str(AUTH_STATE_PATH))
                await install_linkedin_write_guard(context, approval)
                page = await context.new_page()
                await page.goto("https://www.linkedin.com/feed")
                if not page.url.startswith("https://www.linkedin.com/feed"):
                    if headless or unattended:
                        raise LoginRequiredError("LinkedIn session expired; log in again with a visible browser.")
                    logger.info("User is not logged in. Please log in manually...")
                    await page.goto("https://www.linkedin.com/login")
                    await page.wait_for_url("https://www.linkedin.com/feed/**", timeout=120000)
                    logger.info("Login detected. Saving storage state...")
                    await context.storage_state(path=str(AUTH_STATE_PATH))
                yield context, page
            finally:
                if summary := blocked_write_summary():
                    logger.warning(summary)
                await browser.close()
