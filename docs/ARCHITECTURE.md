> **Initial Prompt:** Draft updates to README.md and add or update ARCHITECTURE.md or per-stack docs where useful. Ask before resolving ambiguity. Do not change production behavior

# Architecture

This repo has two stacks: a **Python agent stack** (the LinkedIn automation itself) and an **Azure infra stack** (Bicep/`azd` IaC that provisions the Azure OpenAI resource the agents call). This document describes both, plus known issues to be aware of when making changes.

- [Python Agent Stack](#python-agent-stack)
  - [Purpose](#purpose)
  - [Entry points](#entry-points)
  - [Data layer](#data-layer)
  - [Templates](#templates)
- [Azure Infra Stack](#azure-infra-stack)
  - [Purpose](#purpose-1)
  - [Modules](#modules)
- [Known Issues / Tech Debt](#known-issues--tech-debt)
- [Unenforced Rules](#unenforced-rules)

## Python Agent Stack

### Purpose

AI-powered LinkedIn automation. An LLM (Azure OpenAI, via [Pydantic AI](https://ai.pydantic.dev/)) makes decisions that a [Playwright](https://playwright.dev/python/) browser session then executes against the live LinkedIn UI.

### Entry points

| File | Role |
|---|---|
| `invitations_manager.py` | Scrapes invitation cards, asks an `Agent` to decide accept/ignore/undecided per invitation, clicks the corresponding button. Falls back to loading the full profile page when the agent is undecided. See [Running the invitation manager](../README.md#running-the-invitation-manager). |
| `inbox_manager.py` | Scrapes recent conversations, asks a separate `Agent` to score each thread's reply urgency (1-10), opens the highest-urgency thread. See [Running the inbox manager](../README.md#running-the-inbox-manager). |
| `evals.py` | Runs `pydantic_evals` regression checks (`CorrectDecisionEvaluator`, `IsInstance`) against the invitation-decision agent using cases from `linkedin_invitation_cases.yaml`. Since `agent` is imported directly from `invitations_manager`, it evaluates against whatever `MODEL_BACKEND` resolves to (`ollama` by default). |

### Model backend selection

Both entry points build their Pydantic AI model via a `build_model(backend)` function (`invitations_manager.py:build_model`, `inbox_manager.py:build_model`), selectable per-script via a `--model-backend {ollama,azure,fallback}` CLI flag or the `MODEL_BACKEND` env var:

* **`ollama` (default)** — local [Ollama](https://ollama.com) server via Pydantic AI's `OllamaModel`/`OllamaProvider`, targeting `OLLAMA_MODEL` (default `gemma3:latest`, the 4B tag) at `OLLAMA_BASE_URL` (default `http://localhost:11434/v1`). No Azure credentials are read or required in this mode.
* **`azure`** — Azure OpenAI only, using each script's existing (and intentionally divergent — see Known Issues) client-setup code.
* **`fallback`** — `pydantic_ai.models.fallback.FallbackModel(ollama_model, azure_model)`: tries Ollama first, falls back to Azure OpenAI on failure. **Requires Azure credentials to be present at startup** (not just on failure) since `FallbackModel` constructs both underlying models eagerly. Manually tested (not a regression test) that a connection-refused Ollama endpoint triggered fallback correctly with the library's default `fallback_on=(ModelAPIError,)` on `pydantic-ai==1.107.6` — this relies on how that version wraps connection errors, which is not a documented guarantee, so treat it as verified-for-this-version rather than a permanent contract; a regression test would be a good follow-up if this behavior matters for production use.

Azure client construction is lazy (inside `build_azure_model()`), so importing either module, or running with the default `ollama` backend, never requires `AZURE_TENANT_ID`/`AZURE_OPENAI_*` env vars to be set. See [`docs/reports/local-model-serving-for-gemma3.md`](reports/local-model-serving-for-gemma3.md) for the research behind choosing Ollama over llama.cpp/LM Studio/MLX/vLLM.

### Data layer

No database. All state is file-based:

* `playwright/.auth/state.json` — cached Playwright browser storage state (cookies/session) written after a manual LinkedIn login, so subsequent runs skip re-authenticating. Shared by both `invitations_manager.py` and `inbox_manager.py`.
* `linkedin_invitation_cases.yaml` — eval dataset consumed by `evals.py`; also appended to at runtime by `invitations_manager.py` when run with `--record-eval-cases`.
* `.env` — Azure OpenAI endpoint/deployment config, generated post-provision by `infra/write_dot_env.sh` / `.ps1` (see [Azure Infra Stack](#azure-infra-stack)); also where `MODEL_BACKEND`/`OLLAMA_BASE_URL`/`OLLAMA_MODEL` may optionally be set (these are not `azd`-provisioned outputs, so they are not written by the postprovision hooks).

### Templates

None. LLM system prompts are inline Python strings in `invitations_manager.py` (invitation accept/ignore rules) and `inbox_manager.py` (message urgency scoring rules) — there is no shared prompt-template mechanism.

## Azure Infra Stack

### Purpose

Provisions the Azure OpenAI resource (`gpt-5.5` deployment, per `infra/main.bicep`) that both agent scripts call, using the Azure Developer CLI (`azd`).

### Modules

* `azure.yaml` — `azd` project manifest; wires the `postprovision` hooks.
* `infra/main.bicep` — subscription-scoped: creates a resource group, an Azure OpenAI (Cognitive Services) account with a `gpt-5.5` deployment, and a `Cognitive Services OpenAI User` role assignment.
* `infra/main.parameters.json` — `azd` parameter bindings for the Bicep template.
* `infra/write_dot_env.sh` / `.ps1` — `postprovision` hooks that write `AZURE_TENANT_ID`, `AZURE_OPENAI_SERVICE`, `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_CHAT_DEPLOYMENT`, and `AZURE_OPENAI_CHAT_MODEL` into `.env`.
* `.github/workflows/azure-dev.yaml` — CI provisioning via `azd provision --no-prompt` on push to `main`, using federated OIDC credentials.
* `.github/workflows/template-validation.yaml` — a Microsoft-internal sample-template validation check, inherited from the upstream `Azure-Samples/python-ai-agent-frameworks-demos` template this repo was forked from. Its own header comment says it can be deleted in forks; recommend removing it as part of a future cleanup pass (not done here, to avoid touching CI behavior).

## Known Issues / Tech Debt

* **`inbox_manager.py`'s Azure OpenAI client setup diverges from `invitations_manager.py` and may be broken.** `invitations_manager.py` builds its `AsyncOpenAI` client with `base_url=os.environ["AZURE_OPENAI_ENDPOINT"] + "/openai/v1"`, an async `AzureDeveloperCliCredential`, and the current `OpenAIChatModel` (`invitations_manager.py:34-44`). `inbox_manager.py` instead uses `base_url=os.environ["AZURE_OPENAI_ENDPOINT"]` (no `/openai/v1` suffix), a sync `DefaultAzureCredential`, and the deprecated `OpenAIModel` (`inbox_manager.py:22-30`). This is flagged here for awareness; not fixed, per instruction to avoid changing production behavior.
* **Heavy reliance on CSS selectors / `aria-label` scraping** for both invitation cards (`invitations_manager.py`, `INVITATION_CARD_SELECTORS` and multiple fallback selectors in `get_invitation_info`) and inbox messages (`inbox_manager.py`, `get_inbox_messages`). LinkedIn markup changes will silently break scraping with no compile-time signal.
* **No automated unit tests** — `evals.py` checks LLM output quality, not scraping/parsing logic or CLI behavior.
* **Duplicated boilerplate** between `invitations_manager.py` and `inbox_manager.py`: logging setup, the Playwright login/session-cache flow, and `.auth/state.json` bootstrap are each implemented twice with no shared module.
* **`inbox_manager.py` hard-codes `headless=False`** with no CLI flag, unlike `invitations_manager.py`'s `--headless` option.
* **`ruff` `line-length = 1000`** (`pyproject.toml`) effectively disables line-length linting.
* **Mixed dependency pinning** in `requirements.txt` — `pydantic-ai==1.0.0b1` is pinned to an exact beta version while most other dependencies are unpinned.

## Unenforced Rules

* The invitation accept/ignore business rules ("always ignore wealth/financial advisors", "always ignore coaches", "ignore recruiters") live entirely in the LLM system prompt in `invitations_manager.py` — there is no deterministic keyword/regex check backing these up if the model misclassifies.
* `.pre-commit-config.yaml` defines lint/format/whitespace hooks, but no CI workflow runs them on pull requests (only `azure-dev.yaml`, which provisions infra, and `template-validation.yaml`, which validates the sample-template structure).
* `linkedin_invitation_cases.yaml` has no schema validation on write — `run_and_log_agent` in `invitations_manager.py` appends freeform YAML with no deduplication.
