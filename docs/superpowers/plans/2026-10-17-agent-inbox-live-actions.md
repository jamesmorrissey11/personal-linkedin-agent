# Agent Inbox Live Actions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A decision in Agent Inbox acts on LinkedIn immediately (accept, ignore, send reply, archive), and the daily job only syncs new and already-handled items.

**Architecture:** Each LangGraph review graph gets an async `act` node after its `interrupt`. The node opens a headless,
lock-protected Playwright session with a guard scoped to that one approved action, re-checks LinkedIn, acts,
and either ends the thread with an `outcome` or loops back to the interrupt with a visible error. Read-only page
helpers move into a new `linkedin_pages.py`, so the graph server never imports the LLM manager modules. The
daily job drops its apply steps, deduplicates only against pending items, recovers stuck threads, and detects
archived conversations.

**Tech Stack:** Python 3.13 via `uv`, Playwright (async), LangGraph + `langgraph_sdk`, Agent Inbox (self-hosted), pytest.

**Spec:** [docs/superpowers/specs/2026-10-17-agent-inbox-live-actions-design.md](../specs/2026-10-17-agent-inbox-live-actions-design.md)

**Branch:** `feat/agent-inbox-live-actions-46`, cut from `main` after #43 and #44 merged. The local
`ipykernel` change in `pyproject.toml`/`uv.lock` is unrelated: never stage it.

## Global Constraints

- Nothing is accepted, ignored, sent, or archived on LinkedIn unless a human chose it for that one item in Agent Inbox; the LLM agents keep no tools.
- A message is sent at most once, with exactly the text James submitted.
- An item leaves Agent Inbox only if its LinkedIn action happened, or the item is moot (invitation no longer pending).
- Sync/scrape contexts keep the full write guard, so reading never marks anything read.
- Actions run headless from `playwright/.auth/state.json` and never open a login window.
- LinkedIn sessions are serialized by a file lock at `playwright/.auth/linkedin.lock`. Actions wait up to `LOCK_TIMEOUT_SECONDS = 300` for it.
- Recovery treats a thread as stuck when its status is `error`, or `busy` with `updated_at` older than 10 minutes.
- Thread `outcome` values: `accepted`, `ignored`, `sent`, `archived`, `superseded`, `interrupted`, `legacy`.
- Preserve multi-selector fallback chains; every new selector list gets a fixture test.
- Lint and format with `uv run ruff check --fix .` and `uv run ruff format .`; test with `uv run pytest`.

## Review Focus

1. **Reply text with newlines, emoji, or surrounding spaces:** the sent text must equal the submitted text. Comparison normalizes only `\r\n` and trailing whitespace. Tested in Task 5.
2. **LinkedIn login expired at action time:** the item comes back with "LinkedIn login expired. Log in with a visible browser, then try again." and no browser window opens. Tested in Task 5.
3. **The daily job holds the lock (slow LLM ranking) while James clicks:** the action waits, then after 300 s fails visibly with "Another LinkedIn task is running; try again in a few minutes." Tested in Tasks 1 and 5.
4. **Logged-in name can't be read ("Unknown User"):** the pre-check must still decide by message content: proceed only when the latest message text equals the queued `latest_message`. Tested in Task 5.
5. **Profile URLs that differ only by trailing slash or query string:** the invitation action must still find the card. Tested in Task 5.

---

### Task 1: Shared read-only page helpers and the LinkedIn lock

Move pure Playwright helpers out of the manager modules so `review_graph.py` can use them without importing LLM setup.

**Files:**
- Create: `linkedin_pages.py`
- Modify: `invitations_manager.py`: remove the moved definitions and import them from `linkedin_pages` (keep the names importable from `invitations_manager` for existing tests); `linkedin_session` delegates to `open_linkedin`
- Modify: `inbox_manager.py`: same treatment for its moved helpers and its `linkedin_session`
- Test: `tests/unit/test_linkedin_pages.py`

**Interfaces:**
- Produces, in `linkedin_pages.py`:
  - Moved unchanged from `invitations_manager.py`: `INVITATION_CARD_SELECTORS`, `NO_PENDING_INVITATIONS_TEXT`, `MAX_SCANNED_INVITATIONS`, `get_invitation_cards(page) -> list[ElementHandle]`, `get_invitation_info(card) -> Invitation | None`, `page_reports_no_invitations(page) -> bool`, `collect_invitation_profiles(page) -> tuple[set[str], bool]`, and the `Invitation` model (with `InvitationDecision`/`InvitationAction`, which it references).
  - Moved unchanged from `inbox_manager.py`: `ConversationMessage`, `UNKNOWN_AUTHORS`, `latest_message_is_from_user(messages, logged_in_user) -> bool`, `extract_conversation_messages(page, sender_name) -> list[ConversationMessage]`, `get_logged_in_user_name(page) -> str`, `is_linkedin_conversation_url(value) -> bool`.
  - New: `class LinkedInBusyError(RuntimeError)`.
  - New: `LOCK_PATH = Path("playwright/.auth/linkedin.lock")`.
  - New: `linkedin_lock(timeout_seconds: float, path: Path = LOCK_PATH)`, an async context manager. It holds an exclusive `fcntl.flock` and polls non-blocking once per second; on timeout it raises `LinkedInBusyError`.
  - New: `open_linkedin(headless: bool, unattended: bool, approval: ApprovedAction | None = None, lock_timeout: float = 3600)`, an async context manager yielding `(context, page)`. Its body is today's `linkedin_session`, run under `linkedin_lock`. It passes `approval` to `install_linkedin_write_guard` (the parameter is added in Task 2; until then, call it without `approval`). Batch callers keep the long default timeout; actions pass `LOCK_TIMEOUT_SECONDS`.

- [ ] **Step 1: Write the failing tests**

```python
def test_second_lock_holder_times_out(tmp_path):
    async def scenario():
        async with linkedin_lock(5, tmp_path / "l.lock"):
            with pytest.raises(LinkedInBusyError):
                async with linkedin_lock(1.5, tmp_path / "l.lock"):
                    pass

    run_async_test(scenario)


def test_lock_is_released_after_exit(tmp_path):
    async def scenario():
        async with linkedin_lock(1, tmp_path / "l.lock"):
            pass
        async with linkedin_lock(1, tmp_path / "l.lock"):
            return True

    assert run_async_test(scenario) is True


def test_managers_reexport_moved_helpers():
    import inbox_manager, invitations_manager, linkedin_pages

    assert invitations_manager.get_invitation_info is linkedin_pages.get_invitation_info
    assert inbox_manager.extract_conversation_messages is linkedin_pages.extract_conversation_messages
```

`flock` is per open file description, so the second acquire inside the same process must open its own file handle; it does if `linkedin_lock` opens the path on each entry.

- [ ] **Step 2: Run** `uv run pytest tests/unit/test_linkedin_pages.py -v`. Expected: FAIL with `ModuleNotFoundError: linkedin_pages`.
- [ ] **Step 3: Create `linkedin_pages.py`** with the moved code and the new lock and session. Point both managers at it. `linkedin_pages.py` must not import `pydantic_ai`, `openai`, or `azure`.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all tests pass (111 existing plus 3 new).
- [ ] **Step 5: Commit**: `git commit -m "Extract read-only LinkedIn page helpers and add a session lock"`

---

### Task 2: Guard allows one approved action per context

**Files:**
- Modify: `linkedin_guard.py`
- Test: `tests/unit/test_linkedin_guard.py`, `tests/playwright/test_message_write_guard.py`

**Interfaces:**
- Produces:
  - `ApprovedAction(scope: Literal["invitation", "message"], label: str)`. For `"message"`, `label` is `"send"` or `"archive"`.
  - `install_linkedin_write_guard(context, approval: ApprovedAction | None = None) -> None`
  - `approval_permits(approval, matched: str) -> bool`

**Rules:**
- **No approval:** behavior is unchanged.
- **Approval with scope `"invitation"`:** network and composer guards stay unchanged. `safe_click` permits the matched control, as today.
- **Approval with scope `"message"`:**
  - The composer guard script is not installed.
  - Messaging writes are allowed: read receipts, presence updates, the send itself, and archive.
  - Writes matching `PRIMARY_WRITE_PATTERN = re.compile(r"createMessage|archive", re.I)` are allowed **once** per context. Later matches are aborted and recorded as blocked.
  - `safe_click` permits a destructive match only when `matched == approval.label`. Message/send never unlocks `delete`, `report`, `block`, `leave`, `spam`, or `recall`.

- [ ] **Step 1: Write the failing tests**
  - Unit: replace `test_message_scope_approval_never_unlocks_destructive_clicks` with:
    - `test_message_send_approval_unlocks_only_send`: `ApprovedAction("message", "send")` clicks `Send` (1 click) but refuses `Delete conversation` (0 clicks).
    - `test_message_archive_approval_unlocks_only_archive`.
  - Playwright: add an `approval` parameter to `run_scenario`, defaulting to `None`. New tests:
    - `test_approved_context_allows_exactly_one_send`: two `fetch(WRITE_URL, {method:'POST'})` calls; `hits` has 1 entry and `blocked_writes()` has 1.
    - `test_approved_context_allows_composer_typing`: typing `"hello"` into `#composer` leaves `"hello"`.
    - All existing tests still pass without approval.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_linkedin_guard.py tests/playwright/test_message_write_guard.py -v`. Expected: the new tests FAIL.
- [ ] **Step 3: Implement.** Keep per-context state (the primary-write count) in a closure inside `install_linkedin_write_guard`, not in module globals. Update the module docstring to the new rule: human-approved, per item, single use, and the LLM never acts.
- [ ] **Step 4: Run** the same command. Expected: PASS.
- [ ] **Step 5: Commit**: `git commit -m "Allow one human-approved LinkedIn action per guarded context"`

---

### Task 3: Review queue: pending-only dedupe, outcomes, recovery, legacy

**Files:**
- Modify: `review_queue.py`
- Test: `tests/unit/test_review_queue.py`, plus updates to `tests/unit/test_daily_cadence.py` where it asserts old dedupe or classification

**Interfaces:**
- Produces:
  - `PENDING_STATUSES = {"interrupted", "busy"}`
  - `enqueue_review(client, graph_id, key, input_data) -> bool`: returns False only if a thread for `key` is in `PENDING_STATUSES` without `applied` metadata. Closed threads no longer block re-queuing.
  - `find_pending_review(client, graph_id, key) -> dict | None` replaces `find_review` (update callers in both managers).
  - `fetch_pending_reviews(client, graph_id) -> dict[str, str]`: includes `busy` threads.
  - `classify_review(thread) -> str`: unchanged signature. For pending threads it returns `"already_queued"`.
  - `mark_outcome(client, thread_id, outcome: str, **extra) -> None` sets metadata `{"applied": True, "outcome": outcome, **extra}`. Retire `mark_applied` (and its test) once Task 6 removes the last callers.
  - `recover_stuck_reviews(client, graph_id, now: datetime, busy_after: timedelta = timedelta(minutes=10)) -> int`. For each `error` thread, and each `busy` thread whose `updated_at` is older than `now - busy_after`, it:
    1. cancels its active runs (`client.runs.list` + `client.runs.cancel`);
    2. calls `mark_outcome(..., "interrupted")`;
    3. calls `enqueue_review` with the thread's `values`, minus `decision`/`action`/`reply`/`outcome`, plus `last_error = INTERRUPTED_NOTE`.

    `INTERRUPTED_NOTE = "The last attempt was interrupted; check LinkedIn and choose again."`
  - `retire_legacy_reviews(client, graph_id) -> int`: idle threads with non-empty `values`, no `applied` metadata, and no `values["outcome"]` get `mark_outcome(..., "legacy")`.

Message keys keep today's `conversation_url|sha1(latest)[:12]` format. With pending-only dedupe and the existing "newer message supersedes" logic, that already gives at most one pending item per conversation and needs no key migration.

- [ ] **Step 1: Write the failing tests.** Give `FakeThreads.search` status filtering and add `FakeRuns.list`/`cancel`.
  - `test_enqueue_skips_only_pending_duplicates`: an idle thread for the key → returns True and creates a run. An interrupted one → False.
  - `test_recover_requeues_error_and_old_busy_only`: one `error` thread, one `busy` thread 11 minutes old, one `busy` thread 2 minutes old → returns 2. The two old threads get outcome `interrupted`, two new threads are created with `last_error == INTERRUPTED_NOTE`, and the fresh busy thread is untouched.
  - `test_retire_legacy_marks_unapplied_idle_threads`: an idle thread with `{"decision": "accept"}` and no outcome is marked `legacy`. An idle thread whose `values` has `outcome` is untouched.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_review_queue.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass, after updating the daily-cadence tests whose expectations changed (known-item checks now use `find_pending_review`).
- [ ] **Step 5: Commit**: `git commit -m "Deduplicate reviews against pending items and recover stuck threads"`

---

### Task 4: Capture live LinkedIn markup for action selectors (read-only)

The action selectors can't be guessed. This task records real markup as fixtures, without writing anything to LinkedIn.

**Files:**
- Create: `tests/playwright/fixtures/conversation_thread.html` (an open conversation: message list, composer, send button, conversation options menu expanded to show **Archive**)
- Create: `tests/playwright/fixtures/conversation_archived.html` (an archived conversation, opened from the messaging **Archived** filter)
- Create: `scripts/capture_linkedin_fixtures.py` (one-off; keep it for the next markup drift)

- [ ] **Step 1: Write the capture script.**
  - Use `open_linkedin(headless=True, unattended=True)` with no approval, so the full guard is on.
  - Take a conversation URL as an argument, open it, and use `safe_click` on the conversation options button so the menu is in the DOM. Never click a menu item.
  - Save `page.content()`, with names, message text, and URNs replaced by placeholders.
  - Do the same for an archived conversation chosen from the Archived filter.
- [ ] **Step 2: Run it** against one ordinary and one archived conversation. Ask James for a conversation he doesn't mind being read. Expected: two fixture files, and the log shows no `BLOCKED` UI-layer entries (network-layer blocks of read receipts are expected).
- [ ] **Step 3: Record selector lists** at the top of `linkedin_actions.py` (created in Task 5), at least two fallbacks each, from the fixtures:
  - `COMPOSER_SELECTORS`
  - `SEND_BUTTON_SELECTORS`
  - `CONVERSATION_MENU_SELECTORS`
  - `ARCHIVE_MENU_ITEM_SELECTORS`
  - `ARCHIVED_INDICATOR_SELECTORS`
- [ ] **Step 4: Commit**: `git commit -m "Capture LinkedIn conversation fixtures for action selectors"`

---

### Task 5: LinkedIn action module

**Files:**
- Create: `linkedin_actions.py`
- Test: `tests/unit/test_linkedin_actions.py`, `tests/playwright/test_linkedin_actions.py`

**Interfaces:**
- Consumes: `open_linkedin`, `LinkedInBusyError`, `get_invitation_cards`, `get_invitation_info`, `collect_invitation_profiles`, `extract_conversation_messages`, `get_logged_in_user_name` (Task 1); `ApprovedAction` (Task 2); `LoginRequiredError` from `unattended`.
- Produces:
  - `ActionResult`:

    ```python
    @dataclass
    class ActionResult:
        outcome: Literal["accepted", "ignored", "sent", "archived", "superseded"] | None
        error: str | None = None
        latest_message: str | None = None  # set when a newer incoming message was found
    ```

  - `LOCK_TIMEOUT_SECONDS = 300`
  - `async perform_invitation_action(profile_url: str, decision: Literal["accept", "ignore"]) -> ActionResult`
  - `async perform_message_action(conversation_url: str, action: Literal["reply", "dismiss"], reply: str, expected_latest: str) -> ActionResult`
  - `message_precheck(messages: list[ConversationMessage], logged_in_user: str, expected_latest: str, action: str, reply: str) -> tuple[Literal["proceed", "already_sent", "stop"], str | None]`: the second element is the note shown to James when the verdict is `stop`.
  - `normalize_text(text: str) -> str`: converts `\r\n` to `\n` and strips trailing whitespace on each line and overall.
  - `same_profile(a: str, b: str) -> bool`: compares scheme, host, and path without the trailing slash; ignores query and fragment.
  - `async send_reply(page, text: str) -> bool`, `async archive_conversation(page) -> bool`, `conversation_is_archived(page) -> bool | None`. These are page-level and fixture-tested.

**Behavior (exact notes):**

| Situation | Result |
|---|---|
| `LoginRequiredError` | `ActionResult(None, "LinkedIn login expired. Log in with a visible browser, then try again.")` |
| `LinkedInBusyError` | `ActionResult(None, "Another LinkedIn task is running; try again in a few minutes.")` |
| Invitation not found after a complete scan | `ActionResult("superseded")` |
| Invitation not found after an incomplete scan | error `"Couldn't find this invitation on LinkedIn; it may still be loading. Try again."` |
| Invitation found | click via existing accept/ignore logic with `ApprovedAction("invitation", decision)` → `"accepted"`/`"ignored"` once the card disappears |
| Latest message is from someone else and its text differs from `expected_latest` (rule 5 below) | stop: `"A new message arrived since this was queued; nothing was sent. Review it and choose again."`, with `latest_message` set |
| Reply, and the latest message is from James with text equal to `reply` | `already_sent` → `ActionResult("sent")`, nothing typed |
| Reply, and the latest message is from James with other text | stop: `"You already replied on LinkedIn; nothing was sent. Send this too by choosing again, or Ignore."`, with `latest_message` set to James's text |
| Dismiss, and the latest message is from James | proceed (archive) |
| Unknown user name | decide by content only: proceed iff the latest message text equals `expected_latest` |
| Empty or whitespace-only `reply` | error `"The reply is empty; nothing was sent."` (no browser opened) |
| Composer text after typing ≠ `reply` (normalized) | clear the composer, error `"LinkedIn's message box didn't match your reply; nothing was sent."` |
| Sent message not seen as the latest from James within 15 s | error `"Couldn't confirm the message was sent. Check LinkedIn before trying again."` |

For a reply, a stop verdict triggered by James's own earlier reply is cleared when James chooses again with the same item. The graph stores `result.latest_message` as the item's `latest_message` (Task 6), so on the next attempt rule 2 below matches and the send proceeds.

`message_precheck` evaluates the latest message in this order; the first match wins:
1. `action == "reply"`, the latest message is from James, and its text equals `reply` → `already_sent`.
2. The latest text equals `expected_latest`, whoever wrote it → `proceed`.
3. `action == "dismiss"` and the latest message is from James → `proceed`.
4. `action == "reply"` and the latest message is from James → `stop` with the "You already replied" note.
5. Otherwise → `stop` with the "new message arrived" note.

Every text comparison uses `normalize_text`. If the user name is unknown, no message counts as from James.

Move `execute_approved_action` from `invitations_manager.py` into `linkedin_actions.py` as `async click_invitation_button(card, decision: Literal["accept", "ignore"]) -> bool`, unchanged apart from taking the plain decision string.

Type with `locator.fill` on the first matching composer selector. `linkedin_actions.py` is the only module allowed to call `fill`.

- [ ] **Step 1: Write the failing unit tests.** Monkeypatch `open_linkedin` and the page helpers.
  - `test_precheck_table`: parametrized over every message row above, including the Unknown User case.
  - `test_login_expired_returns_note_without_browser`.
  - `test_busy_lock_returns_note`.
  - `test_empty_reply_fails_without_opening_browser`.
  - `test_same_profile_ignores_trailing_slash_and_query`: `"https://www.linkedin.com/in/ada/?mini=1"` vs `"https://www.linkedin.com/in/ada"` → True.
- [ ] **Step 2: Write the failing Playwright tests.** Serve the Task 4 fixtures behind a fake `linkedin.com` route, as `test_message_write_guard.py` does.
  - `test_send_reply_types_exact_text_and_sends_once`: text `"Thanks!\nSee you Friday 🙂"`; exactly one POST reaches the fake server.
  - `test_send_reply_refuses_when_composer_differs`: the fixture strips emoji on input → returns False, 0 POSTs.
  - `test_archive_conversation_clicks_archive_only`.
  - `test_conversation_is_archived_detects_both_fixtures`: archived → True, ordinary → False.
- [ ] **Step 3: Run** `uv run pytest tests/unit/test_linkedin_actions.py tests/playwright/test_linkedin_actions.py -v`. Expected: FAIL.
- [ ] **Step 4: Implement** `linkedin_actions.py`. Each perform function:
  1. opens `open_linkedin(headless=True, unattended=True, approval=..., lock_timeout=LOCK_TIMEOUT_SECONDS)`;
  2. logs `item`, action, result, and for sends `sha256(reply)[:12]` (never the full text);
  3. converts known exceptions to the notes above;
  4. converts any other exception to `"Couldn't complete the action: {error}"`.
- [ ] **Step 5: Run** the same command. Expected: PASS.
- [ ] **Step 6: Commit**: `git commit -m "Add human-approved LinkedIn actions with re-checks and exact-text sends"`

---

### Task 6: Review graphs act on the decision

**Files:**
- Modify: `review_graph.py`, `scheduling/com.personal-linkedin-agent.langgraph-server.plist` (add `<string>--no-reload</string>` after `--no-browser`, so editing code can't kill an action mid-flight)
- Test: `tests/unit/test_review_graph.py`

**Interfaces:**
- Consumes: `perform_invitation_action`, `perform_message_action`, `ActionResult` (Task 5); `recover_stuck_reviews`, `get_review_client` (Task 3); `unattended.notify`.
- Produces:
  - `ReviewState` adds `last_error: str` and `outcome: str`.
  - `MessageReviewState` adds `last_error: str` and `outcome: str`.
  - `async act_on_invitation(state) -> ReviewState` and `async act_on_message(state) -> MessageReviewState`.
  - `route_after_review(state) -> Literal["act", "__end__"]` (`superseded` → end).
  - `route_after_act(state) -> Literal["review", "__end__"]` (`outcome` set → end, else review).

**Graph shape:** `START → review → (act | END)`, `act → (END | review)`. Message graph: `review_message` and `act_message`.

**Rules:**
- `build_interrupt`/`build_message_interrupt` prefix the description with `⚠️ **Last attempt failed:** {last_error}\n\n` when `last_error` is set.
- `allow_accept = bool(state.get("suggested_reply", "").strip())` for messages.
- On success the act node returns `{"outcome": result.outcome, "last_error": ""}`.
- On failure it returns `{"last_error": result.error, "decision"/"action": None}`, plus `latest_message` when the result has one, and calls `notify("LinkedIn action failed", f"{name}: {result.error}")`.
- On a stop verdict, the act node also writes `result.latest_message` into the state's `latest_message`, so the description shows the current message and the next attempt's pre-check compares against it.
- Each act node first calls `recover_stuck_reviews` best-effort: exceptions are logged and never block the action.

- [ ] **Step 1: Write the failing tests.** Monkeypatch `review_graph.perform_invitation_action`, `perform_message_action`, `recover_stuck_reviews`, and `notify`; drive the graph with `ainvoke` inside `run_async_test`.
  - `test_accept_runs_action_then_ends_with_outcome`: result `"accepted"` → final state `outcome == "accepted"`, and the thread has no pending interrupt.
  - `test_failure_loops_back_to_interrupt_with_note`: first result has an error → `__interrupt__` is present and its description starts with `⚠️ **Last attempt failed:**`. Resuming with ignore and a successful result → `outcome == "ignored"`.
  - `test_superseded_never_calls_action`.
  - `test_message_reply_passes_exact_edited_text`: an edit to `"Friday at 3?"` → `perform_message_action` is called with `reply == "Friday at 3?"`.
  - `test_accept_hidden_without_suggestion`.
  - Update existing graph tests for the async invoke.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_review_graph.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit**: `git commit -m "Act on LinkedIn as soon as a review is resolved in Agent Inbox"`

---

### Task 7: Daily job becomes sync-only

**Files:**
- Modify: `invitations_manager.py`: remove `apply_resolved_invitations`, `approved_invitation_decision`, `ApprovedInvitationAction`, the `apply_inbox_decisions` parameter, and the `--apply-inbox-decisions` flag (`execute_approved_action` already moved in Task 5).
- Modify: `inbox_manager.py`:
  - Remove `apply_message_reviews`, `finalize_dismissed_messages`, the `apply_inbox_decisions` parameter, and the `--apply-inbox-decisions` flag.
  - Rename `close_self_replied_messages` to `close_handled_messages`.
- Modify: `daily_run.py`:
  - Remove `--mode`.
  - Steps, in order: `recover + retire legacy` (both graphs), `invitations cleanup`, `messages cleanup`, `invitations propose`, `messages propose`.
- Delete: `scheduling/com.personal-linkedin-agent.apply-run.plist`.
- Modify: `scheduling/com.personal-linkedin-agent.daily-run.plist` (drop `--mode full`), `scheduling/uninstall.sh` (still boots out `apply-run` if installed).
- Test: `tests/unit/test_daily_cadence.py`

**Interfaces:**
- Consumes: `recover_stuck_reviews`, `retire_legacy_reviews` (Task 3); `conversation_is_archived` (Task 5).
- Produces: `close_handled_messages(page, review_client, logged_in_user) -> int`. It supersedes a pending item when:
  - James sent the latest message (`"You replied on LinkedIn."`);
  - `conversation_is_archived(page) is True` (`"You archived this conversation on LinkedIn."`).

  `None` keeps the item. The newer-message case stays in `send_messages_to_inbox`.
- Produces: the daily summary appends `"{n} old decision(s) from before live actions were retired; anything still open on LinkedIn was queued again"` when `n > 0`. It also reports recovered threads as `"{n} interrupted action(s) brought back for review"`.

- [ ] **Step 1: Write the failing tests.**
  - `test_full_run_orders_sync_steps`: the step names equal the five above.
  - `test_archived_pending_conversation_is_superseded`, and `test_unknown_archive_state_keeps_item`.
  - `test_legacy_and_recovered_counts_appear_in_summary`.
  - `test_previously_dismissed_conversation_is_requeued_when_still_unanswered`: a closed thread for the same key doesn't block `enqueue_review`.
  - Delete `test_apply_mode_never_proposes` and `test_finalize_only_marks_dismissals`.
- [ ] **Step 2: Run** `uv run pytest tests/unit/test_daily_cadence.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `uv run pytest -q`. Expected: all pass.
- [ ] **Step 5: Commit**: `git commit -m "Make the daily job sync-only; actions now happen in Agent Inbox"`

---

### Task 8: Architecture test, docs, and instructions

**Files:**
- Modify: `tests/unit/test_no_message_writes.py`
- Modify: `README.md` (the sections "Human review with Agent Inbox", "No message is sent or deleted without human approval", "Daily unattended workflow", and both CLI flag lists), `scheduling/README.md`
- Modify: `.github/instructions/python.instructions.md` (the safety-invariant bullet and the "No shared module" bullet, which should now mention `linkedin_pages.py`), `.github/copilot-instructions.md` (entry-points table: add `linkedin_pages.py`, `linkedin_actions.py`)
- Comment on #45 (no file edit; its design isn't in this repo): its "Agent Inbox behavior remains unchanged" acceptance line is stale, and its scraper must take `linkedin_lock`

**Rules for the rewritten architecture test:**
- `ACTION_FILES = {"linkedin_actions.py"}` may call `fill` and use composer/send/archive selectors. `linkedin_guard.py` may still call `.click()`.
- Every other root `*.py` keeps today's checks.
- New test `test_actions_always_pass_an_approval`: every `open_linkedin(` call in `linkedin_actions.py` has an `approval=` keyword, and every `safe_click(` call there has an `approval=` keyword (AST check).
- New test `test_only_review_graph_calls_actions`: `perform_invitation_action`/`perform_message_action` are referenced only in `review_graph.py` and tests.
- Keep `test_agents_expose_no_tools` and the prompt-injection test.

- [ ] **Step 1: Rewrite the architecture test.** Run `uv run pytest tests/unit/test_no_message_writes.py -v`. Expected: PASS against Tasks 1-7 (fix any genuine offender instead of widening the allow-list).
- [ ] **Step 2: Update the docs** listed above. New safety rule wording: "Nothing is accepted, ignored, sent, or archived on LinkedIn unless you chose it for that one item in Agent Inbox. The LLM only suggests."
- [ ] **Step 3: Run** `uv run ruff check --fix . && uv run ruff format . && uv run pytest -q`. Expected: clean lint, all pass.
- [ ] **Step 4: Manual end-to-end check with James** (it needs his LinkedIn):
  1. Restart the server: `launchctl kickstart -k gui/$(id -u)/com.personal-linkedin-agent.langgraph-server`.
  2. Ignore one invitation in Agent Inbox → it's gone from the inbox and from LinkedIn's invitation manager.
  3. Reply to one low-stakes conversation with edited text → the text appears on LinkedIn exactly once.
  4. Ignore one conversation → it's archived on LinkedIn.
  5. Run `uv run python daily_run.py --headless` → none of the three come back.
- [ ] **Step 5: Commit**: `git commit -m "Document live Agent Inbox actions and update the write-safety architecture test"`
