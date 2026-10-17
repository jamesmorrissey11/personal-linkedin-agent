from review_queue import enqueue_review, fetch_resolved_reviews, mark_applied
from tests.async_helpers import run_async_test


class FakeThreads:
    def __init__(self, search_results=None):
        self.search_results = search_results or []
        self.created = []
        self.updated = []

    async def search(self, **kwargs):
        return self.search_results

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return {"thread_id": "thread-1"}

    async def update(self, thread_id, **kwargs):
        self.updated.append((thread_id, kwargs))


class FakeRuns:
    def __init__(self):
        self.created = []

    async def create(self, thread_id, graph_id, **kwargs):
        self.created.append((thread_id, graph_id, kwargs))


class FakeClient:
    def __init__(self, search_results=None):
        self.threads = FakeThreads(search_results)
        self.runs = FakeRuns()


def test_enqueue_review_creates_thread_and_run():
    client = FakeClient()

    created = run_async_test(lambda: enqueue_review(client, "graph", "key", {"value": 1}))

    assert created is True
    assert client.threads.created == [{"metadata": {"kind": "graph", "key": "key"}}]
    assert client.runs.created == [("thread-1", "graph", {"input": {"value": 1}})]


def test_enqueue_review_deduplicates_without_starting_run():
    client = FakeClient([{"thread_id": "existing"}])

    created = run_async_test(lambda: enqueue_review(client, "graph", "key", {"value": 1}))

    assert created is False
    assert client.threads.created == []
    assert client.runs.created == []


def test_fetch_resolved_reviews_excludes_unactionable_threads():
    client = FakeClient(
        [
            {"thread_id": "ready", "metadata": {"key": "a"}, "values": {"decision": "accept"}},
            {"thread_id": "applied", "metadata": {"key": "b", "applied": True}, "values": {"decision": "ignore"}},
            {"thread_id": "missing-key", "metadata": {}, "values": {"decision": "accept"}},
            {"thread_id": "empty", "metadata": {"key": "c"}, "values": {}},
        ]
    )

    resolved = run_async_test(lambda: fetch_resolved_reviews(client, "graph"))

    assert resolved == {"a": {"thread_id": "ready", "values": {"decision": "accept"}}}


def test_mark_applied_updates_review_metadata():
    client = FakeClient()

    run_async_test(lambda: mark_applied(client, "thread-1"))

    assert client.threads.updated == [("thread-1", {"metadata": {"applied": True}})]
