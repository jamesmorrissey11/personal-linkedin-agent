"""Client helpers for sending invitations to, and reading resolved reviews from, the LangGraph server."""

import os

from langgraph_sdk import get_client

from review_graph import GRAPH_ID

LANGGRAPH_URL = os.environ.get("LANGGRAPH_URL", "http://localhost:2024")
THREAD_KIND = "invitation_review"


def get_review_client():
    # A local `langgraph dev` server ignores the key; a deployed one needs it.
    api_key = os.environ.get("LANGSMITH_API_KEY") or os.environ.get("LANGSMITH_PERSONAL_ACCESS_TOKEN")
    return get_client(url=LANGGRAPH_URL, api_key=api_key)


async def enqueue_review(client, name: str, profile: str, job_title: str, reason: str) -> bool:
    """Start a review thread for the invitation. Returns False if one already exists for this profile."""
    existing = await client.threads.search(metadata={"kind": THREAD_KIND, "profile": profile}, limit=1)
    if existing:
        return False
    thread = await client.threads.create(metadata={"kind": THREAD_KIND, "profile": profile})
    await client.runs.create(thread["thread_id"], GRAPH_ID, input={"name": name, "profile": profile, "job_title": job_title, "reason": reason})
    return True


async def fetch_resolved_reviews(client) -> dict[str, str]:
    """Map profile URL -> 'accept' | 'ignore' for reviews the human has completed."""
    threads = await client.threads.search(metadata={"kind": THREAD_KIND}, status="idle", limit=100)
    resolved = {}
    for thread in threads:
        decision = (thread.get("values") or {}).get("decision")
        profile = (thread.get("metadata") or {}).get("profile")
        if profile and decision in ("accept", "ignore"):
            resolved[profile] = decision
    return resolved
