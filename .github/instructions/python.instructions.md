---
applyTo: "*.py"
description: Conventions, client-setup pitfalls, lint/format, and test invocation for the Python CLI scripts (invitations_manager.py, inbox_manager.py, evals.py)
---

- Critical inconsistency — do not copy `inbox_manager.py`'s Azure OpenAI client setup:
  `invitations_manager.py` uses `base_url=AZURE_OPENAI_ENDPOINT + "/openai/v1"`, async
  `azure.identity.aio.AzureDeveloperCliCredential`, and the current `OpenAIChatModel`; `inbox_manager.py`
  uses `base_url=AZURE_OPENAI_ENDPOINT` (no `/openai/v1` suffix), sync `azure.identity.DefaultAzureCredential`,
  and the deprecated `OpenAIModel`. When adding a third script or touching agent setup, replicate
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
- Lint/format with `ruff` (`pyproject.toml`, `target-version = "py310"`): run `ruff check --fix .` and
  `ruff format .`. Note `line-length = 1000` effectively disables line-length checks — don't rely on ruff
  to catch overly long lines.
- No CI workflow currently runs lint/pre-commit on PRs (`.github/workflows/` only has `azure-dev.yaml`,
  which provisions Azure infra on push to `main`, and `template-validation.yaml`, which is manual/
  `workflow_dispatch`-only) — run `ruff check --fix .` and `ruff format .` yourself before committing, and
  run `pre-commit install` if working across multiple commits.
- There is no unit test suite. Validate changes to the invitation-decision agent by running
  `python evals.py`, which checks `CorrectDecisionEvaluator`/`IsInstance` against
  `linkedin_invitation_cases.yaml`; there's no mechanism to run a single case in isolation short of
  trimming the YAML file temporarily. `evals.py` does not cover scraping or CLI logic.
