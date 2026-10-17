from datetime import datetime, timedelta, timezone

from linkedin_agent.review.queue import INTERRUPTED_NOTE, enqueue_review, fetch_pending_reviews, fetch_resolved_reviews, find_pending_review, mark_applied, mark_outcome, recover_stuck_reviews, retire_legacy_reviews, supersede_review
from tests.async_helpers import run_async_test

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=timezone.utc)


class FakeThreads:
    def __init__(self, threads=None):
        self.threads = threads or []
        self.created = []
        self.updated = []

    async def search(self, metadata=None, status=None, limit=10, offset=0, **kwargs):
        matches = [t for t in self.threads if (status is None or t.get("status") == status) and all((t.get("metadata") or {}).get(k) == v for k, v in (metadata or {}).items())]
        return matches[offset : offset + limit]

    async def create(self, **kwargs):
        self.created.append(kwargs)
        return {"thread_id": f"new-{len(self.created)}"}

    async def get(self, thread_id):
        return next(t for t in self.threads if t["thread_id"] == thread_id)

    async def update(self, thread_id, **kwargs):
        self.updated.append((thread_id, kwargs))
        for t in self.threads:
            if t["thread_id"] == thread_id:
                t["metadata"] = {**t["metadata"], **kwargs.get("metadata", {})}


class FakeRuns:
    def __init__(self, runs=None):
        self.runs = runs or {}
        self.created = []
        self.cancelled = []
        self.waited = []

    async def create(self, thread_id, graph_id, **kwargs):
        self.created.append((thread_id, graph_id, kwargs))

    async def wait(self, thread_id, graph_id, **kwargs):
        self.waited.append((thread_id, graph_id, kwargs))

    async def list(self, thread_id, **kwargs):
        return self.runs.get(thread_id, [])

    async def cancel(self, thread_id, run_id, **kwargs):
        self.cancelled.append((thread_id, run_id))


class FakeClient:
    def __init__(self, threads=None, runs=None):
        self.threads = FakeThreads(threads)
        self.runs = FakeRuns(runs)


def thread(thread_id, status, key="key", values=None, updated_at=None, **metadata):
    return {"thread_id": thread_id, "status": status, "metadata": {"kind": "graph", "key": key, **metadata}, "values": values or {}, "updated_at": updated_at}


def test_enqueue_review_creates_thread_and_run():
    client = FakeClient()

    created = run_async_test(lambda: enqueue_review(client, "graph", "key", {"value": 1}))

    assert created is True
    assert client.threads.created == [{"metadata": {"kind": "graph", "key": "key"}}]
    assert client.runs.created == [("new-1", "graph", {"input": {"value": 1}})]


def test_enqueue_skips_only_pending_duplicates():
    closed = FakeClient([thread("old", "idle", values={"decision": "ignore"}, applied=True, outcome="ignored")])
    assert run_async_test(lambda: enqueue_review(closed, "graph", "key", {"value": 1})) is True
    assert closed.runs.created == [("new-1", "graph", {"input": {"value": 1}})]

    for status in ("interrupted", "busy"):
        pending = FakeClient([thread("open", status)])
        assert run_async_test(lambda: enqueue_review(pending, "graph", "key", {"value": 1})) is False
        assert pending.threads.created == [] and pending.runs.created == []

    recovered = FakeClient([thread("stuck", "busy", applied=True, outcome="interrupted")])
    assert run_async_test(lambda: enqueue_review(recovered, "graph", "key", {"value": 1})) is True


def test_find_pending_review_ignores_closed_and_applied_threads():
    client = FakeClient([thread("idle", "idle"), thread("stuck", "busy", applied=True), thread("open", "interrupted")])

    assert run_async_test(lambda: find_pending_review(client, "graph", "key"))["thread_id"] == "open"
    assert run_async_test(lambda: find_pending_review(FakeClient([thread("idle", "idle")]), "graph", "key")) is None


def test_fetch_pending_reviews_includes_busy_threads():
    client = FakeClient([thread("a", "interrupted", key="k1"), thread("b", "busy", key="k2"), thread("c", "busy", key="k3", applied=True), thread("d", "idle", key="k4")])

    assert run_async_test(lambda: fetch_pending_reviews(client, "graph")) == {"k1": "a", "k2": "b"}


def test_fetch_resolved_reviews_excludes_unactionable_threads():
    client = FakeClient(
        [
            {"thread_id": "ready", "status": "idle", "metadata": {"kind": "graph", "key": "a"}, "values": {"decision": "accept"}},
            {"thread_id": "applied", "status": "idle", "metadata": {"kind": "graph", "key": "b", "applied": True}, "values": {"decision": "ignore"}},
            {"thread_id": "missing-key", "status": "idle", "metadata": {"kind": "graph"}, "values": {"decision": "accept"}},
            {"thread_id": "empty", "status": "idle", "metadata": {"kind": "graph", "key": "c"}, "values": {}},
        ]
    )

    resolved = run_async_test(lambda: fetch_resolved_reviews(client, "graph"))

    assert resolved == {"a": {"thread_id": "ready", "values": {"decision": "accept"}}}


def test_mark_applied_updates_review_metadata():
    client = FakeClient()

    run_async_test(lambda: mark_applied(client, "thread-1"))

    assert client.threads.updated == [("thread-1", {"metadata": {"applied": True}})]


def test_mark_outcome_sets_applied_outcome_and_extra_metadata():
    client = FakeClient()

    run_async_test(lambda: mark_outcome(client, "thread-1", "sent", sent_text_sha256="abc"))

    assert client.threads.updated == [("thread-1", {"metadata": {"applied": True, "outcome": "sent", "sent_text_sha256": "abc"}})]


def test_recover_requeues_error_and_old_busy_only():
    values = {"name": "Ada", "decision": "accept", "action": "send", "reply": "hi", "outcome": "accepted", "last_error": "old"}
    client = FakeClient(
        [
            thread("errored", "error", key="k-error", values=values),
            thread("old-busy", "busy", key="k-old", values={"name": "Bo"}, updated_at=(NOW - timedelta(minutes=11)).isoformat().replace("+00:00", "Z")),
            thread("fresh-busy", "busy", key="k-fresh", values={"name": "Cy"}, updated_at=NOW - timedelta(minutes=2)),
            thread("handled", "error", key="k-handled", values={"name": "Di"}, applied=True, outcome="interrupted"),
        ],
        runs={"old-busy": [{"run_id": "r1", "status": "running"}, {"run_id": "r0", "status": "success"}], "errored": [{"run_id": "r2", "status": "error"}]},
    )

    recovered = run_async_test(lambda: recover_stuck_reviews(client, "graph", NOW))

    assert recovered == 2
    assert client.runs.cancelled == [("old-busy", "r1")]
    assert client.threads.updated == [("errored", {"metadata": {"applied": True, "outcome": "interrupted"}}), ("old-busy", {"metadata": {"applied": True, "outcome": "interrupted"}})]
    assert client.threads.created == [{"metadata": {"kind": "graph", "key": "k-error"}}, {"metadata": {"kind": "graph", "key": "k-old"}}]
    assert [run[2]["input"] for run in client.runs.created] == [{"name": "Ada", "last_error": INTERRUPTED_NOTE}, {"name": "Bo", "last_error": INTERRUPTED_NOTE}]


def test_retire_legacy_marks_unapplied_idle_threads():
    client = FakeClient(
        [
            thread("legacy", "idle", key="a", values={"decision": "accept"}),
            thread("finished", "idle", key="b", values={"decision": "accept", "outcome": "accepted"}),
            thread("applied", "idle", key="c", values={"decision": "ignore"}, applied=True),
            thread("empty", "idle", key="d"),
            thread("waiting", "interrupted", key="e", values={"name": "Ed"}),
        ]
    )

    retired = run_async_test(lambda: retire_legacy_reviews(client, "graph"))

    assert retired == 1
    assert client.threads.updated == [("legacy", {"metadata": {"applied": True, "outcome": "legacy"}})]


def test_supersede_skips_busy_thread_without_resuming_or_marking():
    client = FakeClient([thread("t1", "busy")])

    assert run_async_test(lambda: supersede_review(client, "t1", "gone")) is False
    assert client.runs.waited == []
    assert client.threads.updated == []


def test_supersede_resumes_and_marks_interrupted_thread():
    client = FakeClient([thread("t1", "interrupted")])

    assert run_async_test(lambda: supersede_review(client, "t1", "gone")) is True
    assert client.runs.waited == [("t1", "graph", {"command": {"resume": [{"type": "superseded", "args": "gone"}]}})]
    assert client.threads.updated == [("t1", {"metadata": {"applied": True, "outcome": "superseded", "superseded_reason": "gone"}})]
