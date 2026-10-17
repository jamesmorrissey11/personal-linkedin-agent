---
title: Testing
description: Commands and coverage for linting, Playwright fixture tests, and LLM evaluations
---

# Testing

Install the locked runtime and development dependencies before running checks:

```shell
uv sync --all-groups
uv run playwright install chromium
```

## Static checks

```shell
uv run ruff check .
uv run ruff format --check .
uv run pre-commit run --all-files
```

## Playwright fixture tests

The pytest suite exercises invitation and inbox scraping behavior against static HTML fixtures. It does
not open LinkedIn or use the cached authenticated browser session.

```shell
uv run pytest -v
```

The tests live under `tests/playwright/` and `tests/unit/`, with pytest configuration in `pyproject.toml`. They import the installed `linkedin_agent` package (`uv sync` installs it in editable mode from `src/`).

## Invitation-decision evaluations

`evals/run.py` runs the invitation-decision agent against `evals/invitation_cases.yaml` using
`CorrectDecisionEvaluator` and `IsInstance`.

```shell
uv run python -m evals.run
```

Ollama is the default model backend. To evaluate Azure OpenAI or the fallback chain instead:

```shell
MODEL_BACKEND=azure uv run python -m evals.run
MODEL_BACKEND=fallback uv run python -m evals.run
```

## Coverage

| Area | Coverage |
|---|---|
| Invitation selectors | Static Playwright fixture tests |
| Inbox selectors and message fields | Static Playwright fixture tests |
| Invitation model decisions | `pydantic_evals` dataset |
| Live LinkedIn compatibility | Manual verification only |
| Login/session flow | Not automated |
| CLI argument behavior | Not automated |
| Eval-case YAML writes | Not automated |
