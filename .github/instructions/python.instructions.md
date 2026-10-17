---
applyTo: "**/*.py"
description: Conventions, client-setup pitfalls, lint/format, and test invocation for the linkedin_agent package (src/linkedin_agent/), its tests, and evals
---

- **Safety invariant: nothing is accepted, ignored, sent, or archived on LinkedIn unless the human chose it for that one item in Agent Inbox; the LLM only suggests.** Sync/scrape contexts stay fully read-only. Only `linkedin/actions.py`, called by `review/graphs.py` after an interrupt resumes, may fill a composer or use send/archive selectors. Every context and `safe_click` in that module must carry the matching single-use `ApprovedAction`; exact reply text is verified before sending. Deleting, reporting, blocking, leaving, spam, recall, and any LLM-initiated or bulk action remain forbidden. `tests/unit/test_no_message_writes.py` enforces the architecture across `src/linkedin_agent/**` and `evals/`.
- Layout (`src/linkedin_agent/`, one entry point `linkedin-agent`, defined in `cli.py`):
  - Workflows, one file each, keep their agent, inline prompt, and workflow together: `invitations.py`,
    `inbox.py`, and `daily.py` (the unattended sync). Each exposes `add_arguments(parser)` and
    `run_command(args)`, which `cli.py` wires up as a subcommand.
  - `llm.py` builds every model backend; `runtime.py` holds shared errors, `ReviewCounts`, console
    logging setup, and notifications.
  - `linkedin/` (everything that touches Playwright/LinkedIn): `models.py`, `session.py`
    (`open_linkedin`, the lock, login detection), `pages.py` (read-only scraping helpers and selector
    fallback chains), `guard.py` (write guard, `safe_click`), and `actions.py` (the only mutations).
  - `review/` (everything that touches LangGraph/Agent Inbox): `graphs.py` (served by `linkedin-agent server` via `deploy/langgraph.json`)
    and `queue.py`.
  - A new workflow is one new module plus a `cli.py` subcommand. Add a subpackage only at a real external
    boundary, and record why.
- Importing any `linkedin_agent` module must need no env vars and make no network or Azure call. Read
  `.env` and set up logging in `cli.main`, read env vars when a model or client is built, and build
  models in each workflow's `configure()` (CLI commands call it at startup so a misconfigured backend
  fails fast).
- Critical inconsistency — the two workflows use different Azure OpenAI client setups, kept side by side
  in `llm.py` behind the explicit `azure_variant` parameter (James's decision in #48: preserve, don't
  unify). `"invitations"` uses `base_url=AZURE_OPENAI_ENDPOINT + "/openai/v1"` and async
  `azure.identity.aio.AzureDeveloperCliCredential`; `"inbox"` uses the bare `AZURE_OPENAI_ENDPOINT` and
  sync `azure.identity.DefaultAzureCredential` (wrapped in an async function so its token provider
  satisfies `AsyncOpenAI`'s typing). A new workflow should use `"invitations"` (the known-working one);
  flag/ask before changing the `"inbox"` variant — this divergence is documented, intentional-until-decided
  tech debt, not an oversight to silently correct.
- Prompts are inline strings, not templates: LLM system prompts (invitation accept/ignore rules, message
  urgency rules) live directly in `invitations.py` and `inbox.py`; there is no Jinja/templating layer.
- Business rules are LLM-judgment only: rules like "always ignore wealth/financial advisors" or "ignore
  recruiters" are text in the system prompt with no deterministic keyword/regex backstop. If asked to make
  a rule more reliable, decide whether it needs code-level enforcement vs. a prompt tweak — don't assume
  one or the other.
- Runtime state is file-based, not env/DB, and lives outside the repo in `runtime.state_dir()`
  (`~/Library/Application Support/linkedin-agent`, override `LINKEDIN_AGENT_HOME`): `browser/state.json` caches
  the Playwright session after a manual LinkedIn login and is used by every session through
  `linkedin.session.open_linkedin`. Never write state or logs relative to the working directory; use the
  `runtime` helpers (`browser_dir`, `langgraph_dir`, `logs_dir`). Tests get an isolated folder automatically
  (`tests/conftest.py`).
- `evals/invitation_cases.yaml` is an append-only eval dataset with no schema validation or dedup —
  `linkedin-agent invitations --record-eval-cases` appends to it freeform.
- Preserve CSS-selector/`aria-label` scraping fallback chains (e.g. `INVITATION_CARD_SELECTORS` in
  `linkedin/pages.py`) when editing scraping logic; don't replace multi-selector fallbacks with a
  single selector, since LinkedIn markup changes can silently break scraping with no compile-time signal.
- Manage dependencies and commands with `uv`: runtime and development dependencies live in
  `pyproject.toml`, exact versions are committed in `uv.lock`, and repository commands should run via
  `uv run`. The package is installed in editable mode by `uv sync`, so tests run against `src/`.
- Lint/format with `ruff` (`pyproject.toml`, `target-version = "py310"`): run
  `uv run ruff check --fix .` and `uv run ruff format .`. Note `line-length = 1000` effectively disables line-length checks — don't rely on ruff
  to catch overly long lines.
- CI (`.github/workflows/ci.yaml`) runs `ruff check`, `ruff format --check`, and `pytest` on pull
  requests. Run `uv run ruff check --fix .` and `uv run ruff format .` yourself before committing, and run
  `uv run pre-commit install` if working across multiple commits.
- Run `uv run pytest` for the unit and fixture-based Playwright tests. Validate changes to the
  invitation-decision agent separately with `uv run python -m evals.run`, which checks
  `CorrectDecisionEvaluator`/`IsInstance` against `evals/invitation_cases.yaml`; there's no mechanism
  to run a single eval case in isolation short of trimming the YAML file temporarily. The evals do not
  cover scraping or CLI logic.
