"""Client helpers for sending items to, and reading resolved reviews from, the LangGraph server."""

import os

from langgraph_sdk import get_client

SEARCH_PAGE_SIZE = 100
LANGGRAPH_URL = os.environ.get("LANGGRAPH_URL", "http://localhost:2024")


def get_review_client():
    # A local `langgraph dev` server ignores the key; a deployed one needs it.
    api_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGSMITH_PERSONAL_ACCESS_TOKEN")
    return get_client(url=LANGGRAPH_URL, api_key=api_key)


async def enqueue_review(client, graph_id: str, key: str, input_data: dict) -> bool:
    """Start a review thread for `key`. Returns False if one already exists."""
    existing = await client.threads.search(metadata={"kind": graph_id, "key": key}, limit=1)
    if existing:
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


async def find_review(client, graph_id: str, key: str) -> dict | None:
    """Return the existing review thread for `key` (in any state), or None."""
    existing = await client.threads.search(metadata={"kind": graph_id, "key": key}, limit=1)
    return existing[0] if existing else None


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
    """Map key -> thread_id for reviews still waiting on a human (shown in Agent Inbox's Interrupted view)."""
    threads = await _search_all_threads(client, metadata={"kind": graph_id}, status="interrupted")
    pending = {}
    for thread in threads:
        metadata = thread.get("metadata") or {}
        if metadata.get("key") and not metadata.get("applied"):
            pending[metadata["key"]] = thread["thread_id"]
    return pending


async def supersede_review(client, thread_id: str, reason: str) -> None:
    """Close a pending review as a no-op by resuming it with a `superseded` response. Never deletes the thread."""
    thread = await client.threads.get(thread_id)
    graph_id = (thread.get("metadata") or {}).get("kind")
    if not graph_id:
        raise ValueError(f"Thread {thread_id} has no graph kind in its metadata")
    await client.runs.wait(thread_id, graph_id, command={"resume": [{"type": "superseded", "args": reason}]})
    await client.threads.update(thread_id, metadata={"applied": True, "outcome": "superseded", "superseded_reason": reason})


async def mark_applied(client, thread_id: str) -> None:
    await client.threads.update(thread_id, metadata={"applied": True})
