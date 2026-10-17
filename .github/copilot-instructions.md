# Copilot Instructions for `personal-linkedin-agent`

> Universal agent entry point: [`AGENTS.md`](../AGENTS.md). Don't start implementation without a
> corresponding GitHub Issue; capture the originating prompt in the issue.

## What this is

A single-stack Python project: an AI-powered LinkedIn automation agent. An LLM (Ollama, OpenAI, or
Azure OpenAI via [Pydantic AI](https://ai.pydantic.dev/)) makes accept/ignore/urgency decisions, and
[Playwright](https://playwright.dev/python/) executes them against the live LinkedIn UI. There is a
supporting Azure infra stack (Bicep/`azd`) that provisions the Azure OpenAI resource the agents call.
There is no frontend/backend split, no database, and no shared library — see "Entry points" below.

## Entry points

| File | Role |
|---|---|
| `invitations_manager.py` | Main CLI. Scrapes invitation cards, runs a `pydantic_ai.Agent` to propose accept/ignore/undecided, and queues actionable proposals for mandatory review. Falls back to loading the full profile page when undecided. |
| `inbox_manager.py` | Secondary CLI. Scrapes recent conversations, runs a separate `Agent` to score each thread's reply urgency (1-10), opens the highest-priority thread. |
| `evals.py` | Runs `pydantic_evals` regression checks (`CorrectDecisionEvaluator`, `IsInstance`) against the invitation-decision agent, using cases from `linkedin_invitation_cases.yaml`. Imports `agent` directly from `invitations_manager`. |
| `daily_run.py` | Unattended orchestrator (apply → close stale → propose → summary notification; `--mode full` or `--mode apply`). Fails open to the inbox, exits non-zero on expired login/health failure. `unattended.py` holds its shared errors, `ReviewCounts`, and `notify`. launchd templates live in `scheduling/`. |
| `review_graph.py` | LangGraph graphs `invitation_review` and `message_review` (`langgraph.json`, served by `uv run langgraph dev`) that interrupt for mandatory human review; normal manager runs queue every proposed action, and `--apply-inbox-decisions` is the only invitation mutation path (messages are never auto-sent). `review_queue.py` is the shared SDK client. The Agent Inbox UI lives in the `agent-inbox/` git submodule (excluded from ruff). |

Run them directly, e.g.:

```shell
uv run python invitations_manager.py --num-to-process 10 [--record-eval-cases] [--headless]
uv run python inbox_manager.py --num-messages 20
uv run python evals.py
```

## Path-scoped rules

Detailed, area-specific rules live in `applyTo`-scoped files under `.github/instructions/` and load
automatically for matching files — don't duplicate them here:

| File | Applies to | Covers |
|---|---|---|
| `instructions/python.instructions.md` | `*.py` | Client-setup divergence between the two manager scripts, no-shared-module/inline-prompt/LLM-judgment conventions, session-state file, scraping fallback chains, ruff lint/format, `evals.py` usage |
| `instructions/infra.instructions.md` | `infra/**` | Bicep resource scope, keeping `write_dot_env.sh`/`.ps1` in sync, not running `azd provision`/`azd down` unprompted |
| `instructions/markdown.instructions.md` | `**/*.md` | Formatting generated Markdown for the Clearance macOS app |

## Organizing Copilot customizations across repos

- Share stable team conventions across repos by templating `.github/copilot-instructions.md`, but keep
  repo-specific build paths and business rules (like the ones in this file's other sections) local to
  this repo's own copy rather than in the shared template.
- Put cross-repo personal workflows, such as commit-message rewriting, in `~/.copilot/skills/` rather
  than duplicating them into this repo.
- Use read-only custom agents for compliance-sensitive specialties such as security review or license
  audit; grant write tools only when remediation is explicitly in scope (see
  `.github/agents/playwright-selector-maintainer.agent.md` for an example of scoping an agent's tools to
  what its task actually needs).

## Agentic-Agile workflow

- Every work request needs a GitHub Issue (use the `agentic-story` template, which includes
  scope, file ownership, and acceptance criteria) before implementation starts.
- Preserve the originating human prompt in the issue's "Originating Prompt" section.
- Don't close, implement, or modify issues labeled `sample`.
- PRs use `.github/pull_request_template.md` and link the issue with `Closes #N`.
- CI (`.github/workflows/ci.yaml`) runs ruff and pytest on PRs; `evals.py` is run manually.

## Maintaining this file

Re-run `/init` after major restructuring or framework changes (e.g. adding a shared module, replacing
Playwright, changing the agent framework). Treat drift between `/init`'s regenerated output and this
file as a diagnostic signal to investigate — e.g. it may reveal a rule that's gone stale — rather than a
patch to apply automatically. Review the diff and merge in only what's still accurate; don't blindly
replace already-reviewed rules with regenerated ones.
