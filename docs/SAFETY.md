---
title: Safety, risks, and recommended practices
---

# Safety, risks, and recommended practices

This project acts on a real LinkedIn account. Its central rule: **nothing is accepted, ignored, sent, or archived on LinkedIn unless you chose it for that one item in Agent Inbox. The LLM only suggests.** This page lists every safeguard with the code and tests that enforce it, the risks that remain, and how to reduce them.

- [Safeguards in place](#safeguards-in-place)
- [Risks](#risks)
- [Recommended practices](#recommended-practices)

## Safeguards in place

| Safeguard | Enforced by | Tested by |
|---|---|---|
| **Every LinkedIn action needs your explicit decision on that one item.** The review graphs pause for Agent Inbox and only act after you resume an item. There are no bulk or auto-approve paths. | [`review/graphs.py`](../src/linkedin_agent/review/graphs.py) (`act` nodes) | [`test_review_graph.py`](../tests/unit/test_review_graph.py) (`test_graph_interrupts_then_resumes_with_action`, `test_superseded_never_calls_action`) |
| **Only one module can change anything on LinkedIn**, and only the review graphs call it. No other code may click outside `safe_click`, type, or use send/composer selectors. | [`linkedin/actions.py`](../src/linkedin_agent/linkedin/actions.py) | [`test_no_message_writes.py`](../tests/unit/test_no_message_writes.py) (`test_only_review_graph_calls_actions`, `test_clicks_only_go_through_safe_click`, `test_no_keyboard_typing_or_filling_in_python_sources`, `test_no_send_or_composer_selectors_in_sources`) |
| **The LLM only suggests.** The agents have no tools; they return structured proposals. | [`invitations.py`](../src/linkedin_agent/invitations.py), [`inbox.py`](../src/linkedin_agent/inbox.py) | `test_agents_expose_no_tools` in [`test_no_message_writes.py`](../tests/unit/test_no_message_writes.py) |
| **One approved write per browser session, enforced at the network layer.** An action's browser context allows exactly one primary write of the approved kind (send or archive) to LinkedIn's confirmed endpoints, plus incidental writes such as read receipts. Everything else is aborted. | `install_linkedin_write_guard` and `ApprovedAction` in [`linkedin/guard.py`](../src/linkedin_agent/linkedin/guard.py) | [`test_linkedin_guard.py`](../tests/unit/test_linkedin_guard.py), [`test_message_write_guard.py`](../tests/playwright/test_message_write_guard.py) (`test_approved_context_blocks_any_second_primary_write`, `test_send_approval_blocks_delete_and_recall_writes`) |
| **Destructive-looking controls are refused** (delete, report, block, leave, spam, recall) unless the approval covers exactly that control. | `safe_click` in [`linkedin/guard.py`](../src/linkedin_agent/linkedin/guard.py) | `test_safe_click_refuses_destructive_elements_without_approval`, `test_message_approval_never_permits_other_destructive_controls` |
| **A reply sends the exact submitted text, once.** The composer contents are checked against your text before sending, and the send counts only once LinkedIn confirms it. | `send_reply` in [`linkedin/actions.py`](../src/linkedin_agent/linkedin/actions.py) | [`test_linkedin_actions.py`](../tests/playwright/test_linkedin_actions.py) (`test_send_reply_types_exact_text_and_sends_once`, `test_send_reply_refuses_when_composer_differs`) |
| **LinkedIn is re-checked before acting.** A new incoming message, or a reply you already sent, stops the action. | `message_precheck` in [`linkedin/actions.py`](../src/linkedin_agent/linkedin/actions.py) | `test_precheck_table` ([unit](../tests/unit/test_linkedin_actions.py)), `test_new_incoming_message_stops_the_action` ([Playwright](../tests/playwright/test_linkedin_actions.py)) |
| **Actions count only when LinkedIn confirms them.** Accept/ignore wait for LinkedIn's response and re-check the invitation list; archive waits for the archive request to succeed. | `perform_invitation_action`, `archive_conversation` in [`linkedin/actions.py`](../src/linkedin_agent/linkedin/actions.py) | `test_invitation_action_reports_failure_when_the_invitation_is_still_pending`, `test_archive_conversation_reports_failure_when_linkedin_never_gets_the_write` |
| **Scraping and the daily sync are read-only.** Their browser contexts have no approval, so every messaging write, including read receipts, is blocked, and nothing is marked read. Typing into a message box is blocked too. | `open_linkedin` in [`linkedin/session.py`](../src/linkedin_agent/linkedin/session.py), [`linkedin/guard.py`](../src/linkedin_agent/linkedin/guard.py) | `test_unapproved_contexts_block_every_messaging_write`, `test_non_get_messaging_requests_are_aborted`, `test_composer_typing_and_enter_are_refused` |
| **Failed or stale actions come back instead of closing.** The item returns to Agent Inbox with a visible note; an interrupted action is never replayed automatically. | [`review/graphs.py`](../src/linkedin_agent/review/graphs.py), `recover_stuck_reviews` in [`review/queue.py`](../src/linkedin_agent/review/queue.py) | `test_failure_loops_back_to_interrupt_with_note` ([`test_review_graph.py`](../tests/unit/test_review_graph.py)), [`test_review_queue.py`](../tests/unit/test_review_queue.py) |
| **Fail open: nothing is hidden.** Undecided or failed LLM proposals are still queued ("Needs your judgment", "Couldn't score"), and stale items are closed only after a full, non-empty scan. | [`invitations.py`](../src/linkedin_agent/invitations.py), [`inbox.py`](../src/linkedin_agent/inbox.py) | `test_failed_and_undecided_invitations_are_queued_for_judgment`, `test_stale_cleanup_never_runs_on_empty_or_incomplete_scans` ([`test_daily_cadence.py`](../tests/unit/test_daily_cadence.py)) |
| **Message text is treated as untrusted.** Prompts wrap it in `<untrusted_message_thread>` and tell the model never to follow instructions inside it; even a successful injection can only change a suggestion. | `rank_messages_for_reply` in [`inbox.py`](../src/linkedin_agent/inbox.py) | `test_prompt_injection_in_message_only_produces_a_ranking` |
| **Newsletter invitations are left pending.** No action exists for them. | [`invitations.py`](../src/linkedin_agent/invitations.py) | `test_newsletter_ignore_button_is_found_by_selector` ([`test_invitation_scraping.py`](../tests/playwright/test_invitation_scraping.py)) |
| **LLM calls are bounded** (`LLM_MAX_TOKENS`, default 512; `LLM_TIMEOUT_SECONDS`, default 60), and the **default backend is local** (Ollama), so no LinkedIn data leaves your machine unless you choose a hosted backend. | `model_settings`, `default_model_backend` in [`llm.py`](../src/linkedin_agent/llm.py) | [`test_llm.py`](../tests/unit/test_llm.py) |
| **One LinkedIn task at a time.** A cross-process lock keeps the daily sync, manual runs, and Agent Inbox actions from using the session simultaneously. | `linkedin_lock` in [`linkedin/session.py`](../src/linkedin_agent/linkedin/session.py) | [`test_linkedin_pages.py`](../tests/unit/test_linkedin_pages.py), [`test_async_no_blocking_calls.py`](../tests/unit/test_async_no_blocking_calls.py) |

CI (`.github/workflows/ci.yaml`) runs all of these tests on every pull request.

## Risks

| Risk | What could happen | Mitigation |
|---|---|---|
| **LinkedIn terms of service and account restrictions** | LinkedIn prohibits most automation. Unusual activity can trigger checks, temporary restrictions, or account suspension. | Keep runs small and daily; actions happen one at a time, only when you decide, and the scrapers stop as soon as they reach items they've already seen. The risk can't be eliminated; use it on your own judgment. |
| **LLM misjudgment** | A wrong proposal (accept a spammer, ignore a contact) or a poor suggested reply. | You decide every item, see the agent's reasoning, and can **Edit** replies. Undecided and failed proposals are labeled. Check evals before trusting a backend. |
| **Prompt injection** via message or profile text | A message tries to make the model do something else. | Text is fenced as untrusted; the model has no tools; the worst case is a bad suggestion that you see before anything is sent. |
| **Selector drift** | LinkedIn changes its page markup, so scraping or an action stops finding elements. | Multi-selector fallback chains; scrapes that find nothing raise a health alert and close nothing; actions confirm with LinkedIn before counting. Fix with the Playwright Selector Maintainer agent. |
| **The cached login session** (`browser/state.json` in the runtime folder) | Anyone with that file can act as you on LinkedIn until the session ends. | It lives outside the repo (never committed) in your per-user folder. See the practices below. |
| **LinkedIn data sent to a hosted model** (`openai`, `azure`, `fallback`) | Invitation and message text leaves your machine for the provider. | The default backend is local Ollama. A hosted backend is used only when you set `MODEL_BACKEND` or pass `--model-backend`. |

## Recommended practices

- **Start small.** Use `--num-to-process` / `--num-messages` (for example 5–10) until you trust the proposals, and keep the daily schedule rather than running often.
- **Check the evals before trusting a backend**: `uv run python -m evals.run` with that backend selected. Small local models vary from run to run.
- **Protect the session file.** Keep the runtime folder (`~/Library/Application Support/linkedin-agent`) out of git, shared drives, and unencrypted backups. Never copy `browser/state.json` anywhere.
- **Log out to invalidate the session** if the machine or the file may have been exposed: sign out of LinkedIn (or "Sign out of all sessions" in LinkedIn's settings), then delete `browser/state.json`. The next run asks you to log in again.
- **Read the note on anything that comes back** with "⚠️ Last attempt failed" before choosing again.
- **Keep the safety tests passing.** Don't bypass `safe_click`, the write guard, or the review graphs; any new LinkedIn write needs the same per-item approval and tests.
