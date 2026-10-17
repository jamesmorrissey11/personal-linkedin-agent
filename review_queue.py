"""Client helpers for sending items to, and reading resolved reviews from, the LangGraph server."""

import os

from langgraph_sdk import get_client

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


async def fetch_resolved_reviews(client, graph_id: str) -> dict[str, dict]:
    """Map key -> {'thread_id', 'values'} for completed reviews that haven't been marked applied."""
    threads = await client.threads.search(metadata={"kind": graph_id}, status="idle", limit=100)
    resolved = {}
    for thread in threads:
        metadata = thread.get("metadata") or {}
        if metadata.get("applied") or not metadata.get("key"):
            continue
        values = thread.get("values") or {}
        if values:
            resolved[metadata["key"]] = {"thread_id": thread["thread_id"], "values": values}
    return resolved


async def mark_applied(client, thread_id: str) -> None:
    await client.threads.update(thread_id, metadata={"applied": True})
