---
applyTo: "*.py"
description: Conventions, client-setup pitfalls, lint/format, and test invocation for the Python CLI scripts (invitations_manager.py, inbox_manager.py, evals.py)
---

- **Safety invariant: no LinkedIn message is ever sent, deleted, archived, reported, blocked, or left without explicit human approval.** Do not add message-write capability. Route every click through `linkedin_guard.safe_click`, install `install_linkedin_write_guard` on every Playwright context, never type or press keys in a composer, and give LLM agents no tools. If sending is ever added it needs per-message approval bound to the conversation URL and the SHA-256 of the exact final text, single use, expiring, and interactive-only; any mismatch fails closed. `tests/unit/test_no_message_writes.py` enforces this in CI.
- Critical inconsistency — do not copy `inbox_manager.py`'s Azure OpenAI client setup:
  `invitations_manager.py` uses `base_url=AZURE_OPENAI_ENDPOINT + "/openai/v1"` and async
  `azure.identity.aio.AzureDeveloperCliCredential`; `inbox_manager.py` uses
  `base_url=AZURE_OPENAI_ENDPOINT` (no `/openai/v1` suffix) and sync `azure.identity.DefaultAzureCredential`
  (wrapped in an async function so its token provider satisfies `AsyncOpenAI`'s typing). Both scripts now
  use the current `OpenAIChatModel`. When adding a third script or touching agent setup, replicate
  `invitations_manager.py`'s pattern (the known-working one); flag/ask before "fixing" `inbox_manager.py` —
  this divergence is documented, intentional-until-decided tech debt, not an oversight to silently correct.
- No shared module: logging setup, the Playwright login/session-cache flow, and CLI arg parsing are each
  implemented independently in `invitations_manager.py` and `inbox_manager.py`. Don't assume a helper in
  one file is reusable — check both files if making a similar change to both.
- Prompts are inline strings, not templates: LLM system prompts (invitation accept/ignore rules, message
  urgency rules) live directly in Python code in each script; there is no Jinja/templating layer.
- Business rules are LLM-judgment only: rules like "always ignore wealth/financial advisors" or "ignore
  recruiters" are text in the system prompt with no deterministic keyword/regex backstop. If asked to make
  a rule more reliable, decide whether it needs code-level enforcement vs. a prompt tweak — don't assume
  one or the other.
- Session/auth state is file-based, not env/DB: `playwright/.auth/state.json` caches the Playwright browser
  session after a manual LinkedIn login and is shared by both manager scripts.
- `linkedin_invitation_cases.yaml` is an append-only eval dataset with no schema validation or dedup —
  `invitations_manager.py --record-eval-cases` appends to it freeform.
- Preserve CSS-selector/`aria-label` scraping fallback chains (e.g. `INVITATION_CARD_SELECTORS` in
  `invitations_manager.py`) when editing scraping logic; don't replace multi-selector fallbacks with a
  single selector, since LinkedIn markup changes can silently break scraping with no compile-time signal.
- Manage dependencies and commands with `uv`: runtime and development dependencies live in
  `pyproject.toml`, exact versions are committed in `uv.lock`, and repository commands should run via
  `uv run`.
- Lint/format with `ruff` (`pyproject.toml`, `target-version = "py310"`): run
  `uv run ruff check --fix .` and `uv run ruff format .`. Note `line-length = 1000` effectively disables line-length checks — don't rely on ruff
  to catch overly long lines.
- No CI workflow currently runs lint/pre-commit on PRs (`.github/workflows/` only has `azure-dev.yaml`,
  which provisions Azure infra on push to `main`, and `template-validation.yaml`, which is manual/
  `workflow_dispatch`-only) — run `uv run ruff check --fix .` and `uv run ruff format .` yourself before
  committing, and run `uv run pre-commit install` if working across multiple commits.
- Run `uv run pytest` for the fixture-based Playwright selector tests. Validate changes to the
  invitation-decision agent separately with `uv run python evals.py`, which checks
  `CorrectDecisionEvaluator`/`IsInstance` against `linkedin_invitation_cases.yaml`; there's no mechanism
  to run a single eval case in isolation short of trimming the YAML file temporarily. `evals.py` does
  not cover scraping or CLI logic.
