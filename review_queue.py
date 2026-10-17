"""Client helpers for sending items to, and reading resolved reviews from, the LangGraph server."""

import logging
import os
from datetime import datetime, timedelta, timezone

from langgraph_sdk import get_client

SEARCH_PAGE_SIZE = 100
LANGGRAPH_URL = os.environ.get("LANGGRAPH_URL", "http://localhost:2024")
PENDING_STATUSES = {"interrupted", "busy"}
ACTIVE_RUN_STATUSES = {"pending", "running"}
INTERRUPTED_NOTE = "The last attempt was interrupted; check LinkedIn and choose again."
RESOLUTION_FIELDS = ("decision", "action", "reply", "outcome")

logger = logging.getLogger("review_queue")


def get_review_client():
    # A local `langgraph dev` server ignores the key; a deployed one needs it.
    api_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGSMITH_PERSONAL_ACCESS_TOKEN")
    return get_client(url=LANGGRAPH_URL, api_key=api_key)


async def enqueue_review(client, graph_id: str, key: str, input_data: dict) -> bool:
    """Start a review thread for `key`. Returns False only if one is still pending; closed threads don't block."""
    if await find_pending_review(client, graph_id, key):
        return False
    thread = await client.threads.create(metadata={"kind": graph_id, "key": key})
    await client.runs.create(thread["thread_id"], graph_id, input=input_data)
    return True


async def _search_all_threads(client, **filters) -> list[dict]:
    """Page through every matching thread instead of stopping at the first page."""
    threads: list[dict] = []
    offset = 0
    while True:
        page = await client.threads.search(limit=SEARCH_PAGE_SIZE, offset=offset, **filters)
        threads.extend(page)
        if len(page) < SEARCH_PAGE_SIZE:
            return threads
        offset += SEARCH_PAGE_SIZE


async def _pending_threads(client, **metadata) -> list[dict]:
    """Threads still waiting on a human or mid-action, excluding ones already closed via metadata."""
    threads = []
    for status in sorted(PENDING_STATUSES):
        threads.extend(t for t in await _search_all_threads(client, metadata=metadata, status=status) if not (t.get("metadata") or {}).get("applied"))
    return threads


async def find_pending_review(client, graph_id: str, key: str) -> dict | None:
    """Return the pending review thread for `key`, or None if every thread for it is closed."""
    pending = await _pending_threads(client, kind=graph_id, key=key)
    return pending[0] if pending else None


def classify_review(thread: dict) -> str:
    """Bucket an existing thread as 'superseded', 'applied', or 'already_queued' for run reports."""
    metadata = thread.get("metadata") or {}
    if metadata.get("outcome") == "superseded":
        return "superseded"
    if metadata.get("applied"):
        return "applied"
    return "already_queued"


async def fetch_resolved_reviews(client, graph_id: str) -> dict[str, dict]:
    """Map key -> {'thread_id', 'values'} for completed reviews that haven't been marked applied."""
    threads = await _search_all_threads(client, metadata={"kind": graph_id}, status="idle")
    resolved = {}
    for thread in threads:
        metadata = thread.get("metadata") or {}
        if metadata.get("applied") or not metadata.get("key"):
            continue
        values = thread.get("values") or {}
        if values:
            resolved[metadata["key"]] = {"thread_id": thread["thread_id"], "values": values}
    return resolved


async def fetch_pending_reviews(client, graph_id: str) -> dict[str, str]:
    """Map key -> thread_id for reviews still waiting on a human or mid-action."""
    pending = {}
    for thread in await _pending_threads(client, kind=graph_id):
        key = (thread.get("metadata") or {}).get("key")
        if key:
            pending[key] = thread["thread_id"]
    return pending


async def supersede_review(client, thread_id: str, reason: str) -> bool:
    """Close a pending review as a no-op by resuming it with a `superseded` response. Never deletes the thread.

    Only interrupted threads are resumed; a busy one is mid-action (stuck ones are left to recovery), so it is
    skipped and False is returned. Returns True when the thread was superseded.
    """
    thread = await client.threads.get(thread_id)
    if thread.get("status") != "interrupted":
        logger.info("Not superseding %s: thread is %s, not interrupted.", thread_id, thread.get("status"))
        return False
    graph_id = (thread.get("metadata") or {}).get("kind")
    if not graph_id:
        raise ValueError(f"Thread {thread_id} has no graph kind in its metadata")
    await client.runs.wait(thread_id, graph_id, command={"resume": [{"type": "superseded", "args": reason}]})
    await mark_outcome(client, thread_id, "superseded", superseded_reason=reason)
    return True


async def mark_applied(client, thread_id: str) -> None:
    await client.threads.update(thread_id, metadata={"applied": True})


async def mark_outcome(client, thread_id: str, outcome: str, **extra) -> None:
    """Close a thread for good: it no longer counts as pending, resolved, stuck, or legacy."""
    await client.threads.update(thread_id, metadata={"applied": True, "outcome": outcome, **extra})


def _as_aware_datetime(value) -> datetime | None:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def recover_stuck_reviews(client, graph_id: str, now: datetime, busy_after: timedelta = timedelta(minutes=10)) -> int:
    """Bring threads stuck in `error`, or `busy` too long, back as fresh pending reviews. Never replays the action."""
    now = _as_aware_datetime(now)
    stuck = await _search_all_threads(client, metadata={"kind": graph_id}, status="error")
    for thread in await _search_all_threads(client, metadata={"kind": graph_id}, status="busy"):
        updated_at = _as_aware_datetime(thread.get("updated_at"))
        if updated_at is not None and updated_at < now - busy_after:
            stuck.append(thread)
    recovered = 0
    for thread in stuck:
        metadata = thread.get("metadata") or {}
        if metadata.get("applied") or not metadata.get("key"):
            continue
        thread_id = thread["thread_id"]
        for run in await client.runs.list(thread_id):
            if run.get("status") in ACTIVE_RUN_STATUSES:
                await client.runs.cancel(thread_id, run["run_id"])
        await mark_outcome(client, thread_id, "interrupted")
        input_data = {k: v for k, v in (thread.get("values") or {}).items() if k not in RESOLUTION_FIELDS}
        await enqueue_review(client, metadata.get("kind") or graph_id, metadata["key"], {**input_data, "last_error": INTERRUPTED_NOTE})
        logger.info("Recovered stuck %s review %s (%s) as a fresh pending item.", graph_id, metadata["key"], thread.get("status"))
        recovered += 1
    return recovered


async def retire_legacy_reviews(client, graph_id: str) -> int:
    """Close threads resolved under the old flow but never applied, so they can't be acted on later."""
    retired = 0
    for thread in await _search_all_threads(client, metadata={"kind": graph_id}, status="idle"):
        values = thread.get("values") or {}
        if not values or values.get("outcome") or (thread.get("metadata") or {}).get("applied"):
            continue
        await mark_outcome(client, thread["thread_id"], "legacy")
        retired += 1
    return retired
