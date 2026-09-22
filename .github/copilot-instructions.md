# Copilot Instructions for `personal-linkedin-agent`

## What this is

A single-stack Python project: an AI-powered LinkedIn automation agent. An LLM (Azure OpenAI via
[Pydantic AI](https://ai.pydantic.dev/)) makes accept/ignore/urgency decisions, and
[Playwright](https://playwright.dev/python/) executes them against the live LinkedIn UI. There is a
supporting Azure infra stack (Bicep/`azd`) that provisions the Azure OpenAI resource the agents call.
There is no frontend/backend split, no database, and no shared library — see "Entry points" below.

## Entry points

| File | Role |
|---|---|
| `invitations_manager.py` | Main CLI. Scrapes invitation cards, runs a `pydantic_ai.Agent` to decide accept/ignore/undecided per invitation, clicks the corresponding button. Falls back to loading the full profile page when undecided. |
| `inbox_manager.py` | Secondary CLI. Scrapes recent conversations, runs a separate `Agent` to score each thread's reply urgency (1-10), opens the highest-priority thread. |
| `evals.py` | Runs `pydantic_evals` regression checks (`CorrectDecisionEvaluator`, `IsInstance`) against the invitation-decision agent, using cases from `linkedin_invitation_cases.yaml`. Imports `agent` directly from `invitations_manager`. |

Run them directly, e.g.:

```shell
python invitations_manager.py --num-to-process 10 [--record-eval-cases] [--headless]
python inbox_manager.py --num-messages 20
python evals.py
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

## Maintaining this file

Re-run `/init` after major restructuring or framework changes (e.g. adding a shared module, replacing
Playwright, changing the agent framework). Treat drift between `/init`'s regenerated output and this
file as a diagnostic signal to investigate — e.g. it may reveal a rule that's gone stale — rather than a
patch to apply automatically. Review the diff and merge in only what's still accurate; don't blindly
replace already-reviewed rules with regenerated ones.
