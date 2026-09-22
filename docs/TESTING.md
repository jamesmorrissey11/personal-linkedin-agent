---
title: Test Setup Summary
description: Inventory of existing test/eval coverage and a recommendation for where a Playwright browser test suite should live
---

# Test Setup Summary

## Existing test/eval framework

- **`pydantic_evals`** is the only quality-check mechanism, driven by `evals.py`. It's an LLM-output
  evaluator, not a unit/integration test framework — it runs the invitation-decision agent (imported from
  `invitations_manager.py`) against cases in `linkedin_invitation_cases.yaml`, scoring with `IsInstance`
  and a custom `CorrectDecisionEvaluator` (exact-match on `.action`).
- **No pytest** (or any xUnit-style framework) is installed — absent from `requirements.txt`, no
  `pytest.ini`/`conftest.py`/`tests/` directory anywhere.
- **No Playwright test runner** (`pytest-playwright`, `@playwright/test`, `playwright.config.*`) exists,
  despite `playwright` (Python, browser-automation only) being a runtime dependency in `requirements.txt`.
- **No CI test step**: `.github/workflows/azure-dev.yaml` only does `azd provision`;
  `.github/workflows/template-validation.yaml` is a manual template-validation job. Neither runs
  `evals.py`, lint, or any tests.
- Local dev tooling (`.pre-commit-config.yaml`, `pyproject.toml`'s `ruff` config) covers lint/format
  only, not testing.

## Coverage by entry-point script

| Script | Test coverage |
|---|---|
| `invitations_manager.py` | Partial — only the LLM decision logic (`agent`/`InvitationDecision`) via `evals.py`. Scraping (`INVITATION_CARD_SELECTORS`, profile fallback), Playwright session/login flow, and CLI arg parsing are **untested**. |
| `inbox_manager.py` | **No coverage at all** — its own separate Agent (urgency scoring), scraping (`query_selector` calls), and Azure client setup (the divergent, possibly-broken one) have zero tests. |
| `evals.py` | N/A — it *is* the test harness, not something tested. |
| `infra/` (Bicep/azd) | No tests; only a manual `template-validation.yaml` workflow (not wired to PRs). |

## Where a Playwright browser test suite should live

Given the project's structure (no `tests/` dir, no shared module, scripts at repo root), a new
browser-automation test suite has no natural home yet. Two viable placements, in order of fit with
existing conventions:

1. **`tests/playwright/`** (new top-level dir) — mirrors the "single-stack, root-level scripts" layout
   without polluting the root with test files; would hold something like
   `test_invitations_manager.py` / `test_inbox_manager.py` using `pytest` + `pytest-playwright`, reusing
   the cached `playwright/.auth/state.json` session.
2. Co-located `test_invitations_manager.py` / `test_inbox_manager.py` at repo root — consistent with the
   current "no subdirectories for code" style, but would mix test and production entry-point scripts in
   the same flat namespace.

Either way, this would require:

- [ ] Adding `pytest` + `pytest-playwright` to `requirements.txt` (currently absent)
- [ ] Adding a `pytest.ini` or `pyproject.toml` `[tool.pytest.ini_options]` block (none exists today)
- [ ] Running against the real, credentialed LinkedIn session rather than a mock — per the documented
      risk in `.github/instructions/python.instructions.md`, the entire value of this suite is catching
      selector drift against the live DOM, which a mock would hide.
