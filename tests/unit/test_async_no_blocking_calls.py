"""Regression tests: the action path must not make blocking calls on the event loop.

`langgraph dev` runs the graphs under blockbuster, which raises BlockingError when synchronous
filesystem or subprocess calls happen inside the running event loop. Because every Agent Inbox
decision is executed by a graph node, a single blocking call makes EVERY action fail -- accepting or
ignoring an invitation, sending a reply, and archiving a conversation all abort before touching
LinkedIn. That is exactly how issue #46 broke in practice while the unit suite stayed green, since
nothing outside `langgraph dev` enabled the detector.

These tests run the same detector so the suite fails the way production does. They are also a real
concurrency guard: the lock waits up to an hour, so blocking on it would freeze the whole server.
"""

import asyncio
import time
from pathlib import Path

import pytest
from blockbuster import BlockingError, blockbuster_ctx

import linkedin_pages
import unattended
from tests.async_helpers import run_async_test


def run_under_blockbuster(scenario):
    """Run `scenario()` on an event loop guarded by blockbuster, as `langgraph dev` does."""

    async def runner():
        with blockbuster_ctx():
            return await scenario()

    return run_async_test(runner)


def test_blockbuster_detects_a_blocking_call(tmp_path: Path):
    """Proves the guard has teeth, so a passing test below is meaningful."""

    async def scenario():
        (tmp_path / "probe").mkdir()

    with pytest.raises(BlockingError):
        run_under_blockbuster(scenario)


def test_linkedin_lock_does_not_block_the_event_loop(tmp_path: Path):
    lock_path = tmp_path / "nested" / "linkedin.lock"

    async def scenario():
        async with linkedin_pages.linkedin_lock(5, lock_path):
            return True

    assert run_under_blockbuster(scenario) is True


def test_linkedin_lock_still_excludes_a_second_holder(tmp_path: Path):
    """The threaded acquisition must not weaken mutual exclusion."""
    lock_path = tmp_path / "linkedin.lock"

    async def scenario():
        async with linkedin_pages.linkedin_lock(5, lock_path):
            with pytest.raises(linkedin_pages.LinkedInBusyError):
                async with linkedin_pages.linkedin_lock(1.5, lock_path):
                    pass
        # The lock is reusable once released.
        async with linkedin_pages.linkedin_lock(5, lock_path):
            return True

    assert run_under_blockbuster(scenario) is True


def test_auth_state_prep_does_not_block_the_event_loop(tmp_path: Path):
    state_path = tmp_path / ".auth" / "state.json"

    async def scenario():
        await linkedin_pages.ensure_auth_state(state_path)

    run_under_blockbuster(scenario)

    # Read outside the guarded loop; the assertion is about production code, not the test's own I/O.
    assert state_path.read_text() == "{}"


def test_auth_state_prep_keeps_an_existing_session(tmp_path: Path):
    state_path = tmp_path / ".auth" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text('{"cookies": ["real-session"]}')

    async def scenario():
        await linkedin_pages.ensure_auth_state(state_path)

    run_under_blockbuster(scenario)

    assert "real-session" in state_path.read_text()


def test_notify_async_runs_the_notifier_off_the_event_loop(monkeypatch, tmp_path: Path):
    """notify() shells out to osascript, which blocks; the async wrapper must offload it."""
    calls = []

    def fake_notify(title: str, message: str) -> None:
        # Stand in for subprocess.run: a genuinely blocking call blockbuster would flag on the loop.
        time.sleep(0.01)
        (tmp_path / "notified").write_text(f"{title}:{message}")
        calls.append((title, message))

    monkeypatch.setattr(unattended, "notify", fake_notify)

    async def scenario():
        await unattended.notify_async("LinkedIn action failed", "Jane Doe: boom")

    run_under_blockbuster(scenario)

    assert calls == [("LinkedIn action failed", "Jane Doe: boom")]


def test_notify_async_does_not_propagate_notifier_failures(monkeypatch):
    """A broken notifier must never abort an action that already happened on LinkedIn."""

    def exploding_notify(title: str, message: str) -> None:
        raise OSError("osascript missing")

    monkeypatch.setattr(unattended, "notify", exploding_notify)

    async def scenario():
        await unattended.notify_async("t", "m")
        return "survived"

    assert run_under_blockbuster(scenario) == "survived"


def test_review_graph_uses_the_async_notifier():
    """Guards against a sync notify() call creeping back into a graph node."""
    source = (Path(__file__).resolve().parents[2] / "review_graph.py").read_text()

    assert "await notify_async(" in source
    assert "\n    notify(" not in source


def test_sleep_in_lock_wait_is_async(tmp_path: Path):
    """time.sleep in the retry loop would block; asyncio.sleep must be used instead."""
    lock_path = tmp_path / "linkedin.lock"
    ticks = []

    async def scenario():
        async with linkedin_pages.linkedin_lock(5, lock_path):

            async def heartbeat():
                for _ in range(3):
                    await asyncio.sleep(0.05)
                    ticks.append(1)

            beat = asyncio.create_task(heartbeat())
            with pytest.raises(linkedin_pages.LinkedInBusyError):
                async with linkedin_pages.linkedin_lock(0.4, lock_path):
                    pass
            await beat

    run_under_blockbuster(scenario)

    # The event loop kept running other tasks while the lock was being awaited.
    assert len(ticks) == 3
