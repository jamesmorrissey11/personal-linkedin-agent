# Copilot Instructions

> This file provides GitHub Copilot with project-specific context. For the universal cross-agent entry point used by this project, see [`AGENTS.md`](../../../AGENTS.md).

## Project Description

<!-- Replace this with a 2-3 sentence description of your project. -->
<!-- Example: "A REST API for task management built with Node.js and Express. Uses PostgreSQL for storage and JWT for authentication." -->

AI-powered LinkedIn automation agent. Azure OpenAI (via Pydantic AI) decides accept/ignore/urgency; Playwright executes against the live LinkedIn UI. See `.github/copilot-instructions.md` for the full, authoritative context.

## Coding Style

<!-- Define the conventions Copilot should follow when generating code. -->

- **Language:** Python >=3.10, managed with `uv`
- **Formatting:** `ruff check --fix` and `ruff format` (line-length effectively unenforced)
- **Naming:** snake_case functions/variables, PascalCase classes, UPPER_SNAKE constants
- **Imports:** group stdlib / third-party / local (ruff-managed)
- **Error handling:** do not swallow scraping failures silently; log them

## Testing Approach

<!-- Describe how tests should be written and organized. -->

- **Framework:** pytest + pytest-playwright (HTML fixtures); `uv run python -m evals.run` for agent decisions
- **Location:** `tests/unit/` and `tests/playwright/`
- **Naming:** `test_*.py`, `test_<behavior>` functions
- **Coverage expectations:** new scraping paths get a fixture-based test

## File Structure

<!-- Describe the project layout so Copilot understands where things belong. -->

```
project-root/
├── src/              # Application source code
├── tests/            # Test files
├── docs/             # Documentation
├── .github/          # GitHub configuration
└── ...
```

## Key Conventions

<!-- List project-specific conventions that affect code generation. -->

- Prompts are inline strings; business rules are LLM-judgment only (see `.github/instructions/python.instructions.md`)
- Preserve multi-selector / `aria-label` fallback chains when editing scraping logic
- Runtime state (LinkedIn session, Agent Inbox data, logs) lives outside the repo in the per-user runtime folder; never commit it

## What Not to Do

<!-- Explicit anti-patterns to avoid. -->

- Do not copy the `"inbox"` Azure OpenAI client variant in `src/linkedin_agent/llm.py`; follow the `"invitations"` variant
- Do not commit secrets or credentials
- Do not add dependencies without documenting the reason (`uv add`, commit `uv.lock`)
- Do not start implementation without a corresponding GitHub Issue. Every work request must be tracked.
- Do not discard the originating human prompt — capture it in the issue's "Originating Prompt" section or as a comment for retrospective use.
- Do not close, implement, or modify issues labeled `sample`. These are onboarding references (prefixed `[SAMPLE 1]`, `[SAMPLE 2]`), not actionable work items.
