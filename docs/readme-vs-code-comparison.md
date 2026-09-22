> **Initial Prompt:** Compare what you found against README.md and existing docs. What is missing, outdated, contradictory, or wrong? Cite the files that establish the current behavior

# Comparison: README.md & docs vs. actual code behavior

Cross-checked `README.md` and `docs/repo-summary.md` against `invitations_manager.py`, `inbox_manager.py`, `azure.yaml`, `infra/main.bicep`, `infra/write_dot_env.sh`, `.devcontainer/*`, and `.pre-commit-config.yaml`.

## Missing from README

| Gap | Evidence |
|---|---|
| **`inbox_manager.py` isn't documented at all** — no "Running the inbox manager" section, despite being a second, fully-implemented entry point. | File exists and is functional (`inbox_manager.py:1-260`); README only has a "Running the invitation manager" section. |
| **No Playwright browser install step.** `playwright` is a pip package only; browser binaries (`playwright install chromium`) are never installed in setup instructions or the devcontainer. | `requirements.txt` lists `playwright`; `.devcontainer/Dockerfile` only runs `pip install -r requirements.txt`; README's "Local environment" section stops at `pip install -r requirements.txt`. Without this step, `async_playwright().chromium.launch()` in both scripts will fail on a fresh setup. |
| **No mention of CLI flags** (`--num-to-process`, `--record-eval-cases`, `--headless`, `--num-messages`). | Defined via `argparse` in `invitations_manager.py:363-368` and `inbox_manager.py:257-259`. |
| **No mention of the manual first-run LinkedIn login flow** or `playwright/.auth/state.json` session cache. | `invitations_manager.py:246-256`, `inbox_manager.py:214-221`. |
| **No mention of `linkedin_invitation_cases.yaml`** as the evals dataset/log file that `evals.py` and `--record-eval-cases` depend on. | `evals.py:17`, `invitations_manager.py:80-99`. |

## Outdated / stale

| Issue | Evidence |
|---|---|
| **README still branded as the upstream template** `python-ai-agent-frameworks-demos` (badges, clone URL, "cd python-ai-agents-demos"), not this fork/repo `personal-linkedin-agent`. | `README.md` badges/links point to `Azure-Samples/python-ai-agent-frameworks-demos`; `.devcontainer/devcontainer.json` name field is also still `"python-ai-agent-frameworks-demos"`. Actual repo is `jamesmorrissey11/personal-linkedin-agent` (per `azure.yaml:3`: `name: personal-linkedin-agent`). |
| **`.github/workflows/template-validation.yaml`** is explicitly labeled internal-Microsoft-only ("You can delete this in your fork") but still present — a leftover from the template, not cleaned up for this fork. | `.github/workflows/template-validation.yaml:1` comment. |

## Contradictory / inconsistent (code vs. code, not just vs. docs)

| Issue | Evidence |
|---|---|
| **`inbox_manager.py`'s Azure OpenAI client setup is inconsistent with `invitations_manager.py`** and likely broken: it builds `base_url=os.environ["AZURE_OPENAI_ENDPOINT"]` with no `/openai/v1` suffix and uses the deprecated `OpenAIModel` + sync `DefaultAzureCredential`, while `invitations_manager.py` correctly appends `/openai/v1` and uses `OpenAIChatModel` + async `AzureDeveloperCliCredential`. | `inbox_manager.py:22-30` vs `invitations_manager.py:34-44`. Since the README doesn't document `inbox_manager.py` at all, this divergence/bug is currently invisible to a reader relying only on README. |
| **`azure.yaml` metadata still says `template: personal-linkedin-agent@0.0.1`** with no version history/changelog anywhere to confirm what that version means — nothing else in the repo references or updates this version. | `azure.yaml:4`. |

## Wrong / would mislead a new user

- README's "Configuring Azure AI models" section is accurate against `infra/main.bicep` (model `gpt-5.5`, hooks match `write_dot_env.sh`), so no contradiction there — this part is correct and up to date.
- Nothing in README claims inbox-triage behavior, so no direct factual contradiction, but its total silence on `inbox_manager.py` is misleading by omission given it's presented as "the agent" (singular) when there are two independent agents/scripts.

## Net effect on `docs/repo-summary.md`

The summary is consistent with actual code (verified directly against source), and it already flagged the `invitations_manager.py`/`inbox_manager.py` client divergence as tech debt — but README doesn't corroborate or even acknowledge `inbox_manager.py`'s existence, so a reader following only README would never discover that inconsistency. Recommend updating README to cover `inbox_manager.py`, the Playwright install step, CLI flags, and rebrand away from the upstream template name.
