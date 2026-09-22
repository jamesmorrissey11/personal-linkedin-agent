# Delegation brief: Playwright + pytest test backfill

**Audience:** Copilot cloud agent
**Repo:** `personal-linkedin-agent`
**Base branch:** `test-suite-foundation`

## Context

A minimal Playwright test setup was added locally: `tests/playwright/` with static HTML
fixtures under `tests/playwright/fixtures/`, loaded via `page.goto(f"file://...")` so the
suite never drives a live, credentialed LinkedIn session and never touches
`playwright/.auth/state.json`. Pytest config lives in `pyproject.toml` under
`[tool.pytest.ini_options]` (no separate `pytest.ini`). Test-only dependencies
(`pytest`, `pytest-playwright`) are declared in `requirements-dev.txt`, which layers on
top of `requirements.txt`.

Two test modules already exist and pass:
- `tests/playwright/test_invitation_scraping.py` — exercises `INVITATION_CARD_SELECTORS`
  and the Accept/Ignore `aria-label` selectors from `invitations_manager.py`.
- `tests/playwright/test_inbox_scraping.py` — exercises the conversation-list and
  message-event selectors from `inbox_manager.py`.

This brief asks you to expand that foundation.

## Primary goal: expand Playwright scraping-selector coverage

- Continue loading static HTML fixtures under `tests/playwright/fixtures/` via
  `page.goto(f"file://...")` — never a live, credentialed LinkedIn session, and never touch
  `playwright/.auth/state.json`.
- Prefer the same `aria-label`/role-based locators and CSS-selector fallback chains already
  used in `invitations_manager.py` (`INVITATION_CARD_SELECTORS`) and `inbox_manager.py`,
  rather than inventing new selector strategies.
- Cover additional scraping/interaction paths not yet exercised:
  - The accept/ignore button click flow (`execute_action` in `invitations_manager.py`).
  - The newsletter auto-ignore loop (`ignore_newsletter_invitations` in
    `invitations_manager.py`).
  - Profile-page fallback text extraction (the `main, div[role='main']` wait-for-selector
    path used when a profile page partially loads).
  - The inbox conversation-opening/message-ordering flow in `inbox_manager.py`
    (`li.msg-conversation-listitem` → `li.msg-s-message-list__event` sequence, including the
    author/content/timestamp fallback selectors).
- Add new fixture HTML files under `tests/playwright/fixtures/` as needed to cover these
  paths (e.g. a fixture with no accept button present, a fixture with multiple newsletter
  invites, a fixture representing a partially-loaded profile page).

## Secondary goal: pytest backfill for non-browser logic

- Add pytest backfill coverage (non-Playwright, non-browser) for the LLM-decision logic
  seams in `invitations_manager.py` and `inbox_manager.py` — e.g. `InvitationDecision`/
  `MessageRanking` model validation, and any pure-Python helper functions — by mocking the
  `pydantic_ai.Agent`/`AsyncOpenAI` calls rather than hitting Azure OpenAI.
- Add regression coverage that loads `linkedin_invitation_cases.yaml` and asserts it parses
  into valid eval cases (schema/shape only, not live model grading), complementing but not
  duplicating `evals.py`.

## Constraints

- Do not change `invitations_manager.py`, `inbox_manager.py`, `evals.py`, or any other
  production code.
- Do not add new dependencies beyond `pytest`/`pytest-playwright` (already added) unless
  strictly required for mocking; if one is added, declare it in `requirements-dev.txt` so
  tests run from a clean install.
- Keep pytest config in `pyproject.toml` under `[tool.pytest.ini_options]` — no separate
  `pytest.ini`.
- Use Chromium only.
- Mock the Azure OpenAI/`pydantic_ai` agent calls instead of requiring real Azure
  credentials or network access.
- If a real production bug or scraping-selector mismatch blocks a test, document it in the
  PR instead of fixing it.
- Include exact commands run (`pip install -r requirements-dev.txt`,
  `python -m playwright install chromium`, `pytest -v`) and their results in the PR
  description.
- Follow this repo's contribution workflow: file the issue with
  `.github/ISSUE_TEMPLATE.md`, link it from the PR with `Closes #NUMBER`, and follow
  `.github/CONTRIBUTING.md` guidance for branch naming and commits.

## Definition of done

- A draft PR against `test-suite-foundation` adding tests under `tests/playwright/`.
- All new and existing tests pass via `pytest -v`.
- An issue exists (filed with `.github/ISSUE_TEMPLATE.md`) and is linked from the PR via
  `Closes #NUMBER`.
- The PR description includes the exact commands run and their results.
- Any blocking production bugs or selector mismatches are documented in the PR, not fixed.
