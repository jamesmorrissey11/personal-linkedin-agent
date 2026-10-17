# Copilot Instructions for `personal-linkedin-agent`

> Universal agent entry point: [`AGENTS.md`](../AGENTS.md). Don't start implementation without a
> corresponding GitHub Issue; capture the originating prompt in the issue.

## What this is

A single-stack Python project: an AI-powered LinkedIn automation agent. An LLM (Ollama, OpenAI, or
Azure OpenAI via [Pydantic AI](https://ai.pydantic.dev/)) makes accept/ignore/urgency decisions, and
[Playwright](https://playwright.dev/python/) executes them against the live LinkedIn UI. There is a
supporting Azure infra stack (Bicep/`azd`) that provisions the Azure OpenAI resource the agents call.
There is no frontend/backend split or database. The Python code is one installable package, `src/linkedin_agent/`, with a single CLI, `linkedin-agent`.

## Entry points

| Path | Role |
|---|---|
| `src/linkedin_agent/cli.py` | The `linkedin-agent` command (`[project.scripts]`): `invitations`, `inbox`, and `daily` subcommands. Loads `.env` and sets up logging at startup; nothing happens at import. |
| `src/linkedin_agent/invitations.py` | Invitation workflow: scrapes invitation cards, runs a `pydantic_ai.Agent` to propose accept/ignore/undecided, and queues every new invitation for mandatory review. Falls back to loading the full profile page when undecided. |
| `src/linkedin_agent/inbox.py` | Inbox workflow: scans conversations until caught up, runs a separate `Agent` to score reply urgency (1-10) and suggest a reply, queues conversations where someone else spoke last, and opens the highest-priority thread in interactive runs. |
| `src/linkedin_agent/daily.py` | Sync-only unattended orchestrator (recover/retire → close handled → propose → summary). It never writes to LinkedIn and exits non-zero on expired login/health failure. launchd templates live in `deploy/launchd/`. |
| `src/linkedin_agent/llm.py` | Every model backend (`ollama`, `openai`, `azure`, `fallback`), with the two preserved Azure client variants. `runtime.py` holds shared errors, `ReviewCounts`, logging setup, and `notify`. |
| `src/linkedin_agent/linkedin/` | Everything that touches Playwright/LinkedIn: `models.py`, `session.py` (cached-login context, cross-process lock), `pages.py` (read-only selectors/helpers), `guard.py` (default-deny write guard, `safe_click`, single-use `ApprovedAction`), and `actions.py` (the only mutation module: one explicitly approved accept/ignore/send/archive). |
| `src/linkedin_agent/review/` | Everything that touches LangGraph/Agent Inbox: `graphs.py` (graphs `invitation_review` and `message_review`, served by `uv run linkedin-agent server` via `deploy/langgraph.json`, which interrupt for review and then call `linkedin/actions.py`) and `queue.py` (the SDK client). The Agent Inbox UI lives in the `deploy/agent-inbox/` git submodule (James's fork; excluded from ruff). |
| `evals/run.py` | `pydantic_evals` regression checks (`CorrectDecisionEvaluator`, `IsInstance`) against the invitation-decision agent, using `evals/invitation_cases.yaml`. Developer-only; not part of the package. |

Run them with `uv run`, e.g.:

```shell
uv run linkedin-agent invitations --num-to-process 10 [--record-eval-cases] [--headless]
uv run linkedin-agent inbox --num-messages 20
uv run linkedin-agent daily --headless
uv run python -m evals.run
```

## Repository layout

| Path | Contents |
|---|---|
| `src/linkedin_agent/` | All application code (the only code that runs) |
| `tests/` | Unit and fixture-based Playwright tests |
| `evals/` | Developer-only LLM evals |
| `scripts/` | One-off developer scripts (fixture capture, runtime-state migration) |
| `deploy/` | How it runs: `langgraph.json` (server config), `launchd/` (scheduled jobs), `azure/` (`azd` provisioning: `azure.yaml`, `infra/`), and the `agent-inbox/` UI submodule |
| `docs/` | Architecture, testing, style, the Agentic-Agile manifesto, platform adapters, and design specs/plans |

Runtime state (LinkedIn session, lock, Agent Inbox data, logs) never lives in the repo: see `linkedin_agent.runtime.state_dir()`
(`~/Library/Application Support/linkedin-agent` on macOS, override with `LINKEDIN_AGENT_HOME`). Don't add code that writes
files relative to the working directory; use the `runtime` folder helpers.

## Safety invariant

Nothing is accepted, ignored, sent, or archived on LinkedIn unless the human chose it for that one item in
Agent Inbox; the LLM only suggests. Sync contexts remain fully read-only. `linkedin/actions.py` is the only
mutation module, and every action uses a matching single-use `ApprovedAction`, re-checks live state, and
verifies exact reply text. Deleting, reporting, blocking, leaving, recalling, bulk actions, and LLM-initiated
actions remain forbidden. `tests/unit/test_no_message_writes.py` fails CI on architecture violations.

## Path-scoped rules

Detailed, area-specific rules live in `applyTo`-scoped files under `.github/instructions/` and load
automatically for matching files — don't duplicate them here:

| File | Applies to | Covers |
|---|---|---|
| `instructions/python.instructions.md` | `**/*.py` | Package layout, import-time rules, the preserved Azure client variants, inline-prompt/LLM-judgment conventions, session-state file, scraping fallback chains, ruff lint/format, evals usage |
| `instructions/infra.instructions.md` | `deploy/azure/**` | Bicep resource scope, keeping `write_dot_env.sh`/`.ps1` in sync, not running `azd provision`/`azd down` unprompted |
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
- CI (`.github/workflows/ci.yaml`) runs ruff and pytest on PRs; the evals (`uv run python -m evals.run`) are run manually.

## Maintaining this file

Re-run `/init` after major restructuring or framework changes (e.g. adding a shared module, replacing
Playwright, changing the agent framework). Treat drift between `/init`'s regenerated output and this
file as a diagnostic signal to investigate — e.g. it may reveal a rule that's gone stale — rather than a
patch to apply automatically. Review the diff and merge in only what's still accurate; don't blindly
replace already-reviewed rules with regenerated ones.
