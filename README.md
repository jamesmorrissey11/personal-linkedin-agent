# Personal AI Agent for LinkedIn

[![Open in GitHub Codespaces](https://img.shields.io/static/v1?style=for-the-badge&label=GitHub+Codespaces&message=Open&color=brightgreen&logo=github)](https://codespaces.new/jamesmorrissey11/personal-linkedin-agent)
[![Open in Dev Containers](https://img.shields.io/static/v1?style=for-the-badge&label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/jamesmorrissey11/personal-linkedin-agent)

This repository provides an AI-powered agent for managing personal LinkedIn accounts. The agent uses [Pydantic AI](https://ai.pydantic.dev/) for LLM-based decisions and [Playwright](https://playwright.dev/python/) for browser automation. It can process LinkedIn invitations, deciding whether to accept or ignore them based on customizable criteria. See [the demo video](https://www.youtube.com/live/-OsgE9yBkFE) to see the agent in action.

- [Personal AI Agent for LinkedIn](#personal-ai-agent-for-linkedin)
  - [Getting started](#getting-started)
    - [GitHub Codespaces](#github-codespaces)
    - [VS Code Dev Containers](#vs-code-dev-containers)
    - [Local environment](#local-environment)
  - [Configuring Azure AI models](#configuring-azure-ai-models)
  - [Configuring OpenAI models](#configuring-openai-models)
  - [Configuring Ollama Models](#configuring-ollama-models)
  - [Running the invitation manager](#running-the-invitation-manager)
  - [Running the inbox manager](#running-the-inbox-manager)
  - [Running evaluations](#running-evaluations)
  - [Cost estimate](#cost-estimate)
  - [Architecture](#architecture)
  - [Resources](#resources)

## Getting started

You have a few options for getting started with this repository.
The quickest way to get started is GitHub Codespaces, since it will setup everything for you, but you can also [set it up locally](#local-environment).

### GitHub Codespaces

You can run this repository virtually by using GitHub Codespaces. The button will open a web-based VS Code instance in your browser:

1. Open the repository (this may take several minutes):

    [![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/jamesmorrissey11/personal-linkedin-agent)

2. Open a terminal window
3. Continue with the steps to run the examples

### VS Code Dev Containers

A related option is VS Code Dev Containers, which will open the project in your local VS Code using the [Dev Containers extension](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers):

1. Start Docker Desktop (install it if not already installed)
2. Open the project:

    [![Open in Dev Containers](https://img.shields.io/static/v1?style=for-the-badge&label=Dev%20Containers&message=Open&color=blue&logo=visualstudiocode)](https://vscode.dev/redirect?url=vscode://ms-vscode-remote.remote-containers/cloneInVolume?url=https://github.com/jamesmorrissey11/personal-linkedin-agent)

3. In the VS Code window that opens, once the project files show up (this may take several minutes), open a terminal window.
4. Continue with the steps to run the examples

### Local environment

1. Make sure the following tools are installed:

    * [uv](https://docs.astral.sh/uv/getting-started/installation/)
    * Git

2. Clone the repository:

    ```shell
    git clone https://github.com/jamesmorrissey11/personal-linkedin-agent
    cd personal-linkedin-agent
    ```

3. Create the virtual environment and install runtime and development dependencies:

    ```shell
    uv sync --all-groups
    ```

    `uv` installs a compatible Python 3.10+ interpreter when needed and manages the project's `.venv`
    automatically, so manual activation is not required.

4. Install the Playwright browser binaries (required once per environment; the Python package alone does not include them):

    ```shell
    uv run playwright install chromium
    ```


## Configuring Azure AI models

This project uses Azure OpenAI and includes infrastructure as code (IaC) to provision a `gpt-5.5` deployment. The IaC is defined in the `infra` directory and uses the Azure Developer CLI. Provisioned resources incur Azure costs.

1. Make sure the [Azure Developer CLI (azd)](https://aka.ms/install-azd) is installed.

2. Login to Azure:

    ```shell
    azd auth login
    ```

    For GitHub Codespaces users, if the previous command fails, try:

   ```shell
    azd auth login --use-device-code
    ```

3. Provision the OpenAI account:

    ```shell
    azd provision
    ```

    It will prompt you to provide an `azd` environment name (like "agents-demos"), select a subscription from your Azure account, and select a location. Then it will provision the resources in your account.

4. Once the resources are provisioned, you should now see a local `.env` file with all the environment variables needed to run the scripts.
5. To delete the resources, run:

    ```shell
    azd down
    ```

## Configuring OpenAI models

Both manager scripts can use the standard OpenAI API directly. Add these values to `.env`:

```shell
MODEL_BACKEND=openai
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4.1-mini
```

`OPENAI_MODEL` is optional and defaults to `gpt-4.1-mini`. The API key is required whenever
`MODEL_BACKEND=openai` or `--model-backend openai` is selected.

You can select OpenAI for an individual run without changing `MODEL_BACKEND`:

```shell
uv run python invitations_manager.py --model-backend openai
uv run python inbox_manager.py --model-backend openai
```

## Configuring Ollama Models

Both agent scripts can run against a local [Ollama](https://ollama.com) model instead of (or as a
fallback for) Azure OpenAI. **Ollama is the default backend** — you can run either script without any
Azure setup at all as long as Ollama is installed and running locally.

1. [Install Ollama](https://ollama.com/download) and start it (`ollama serve`, or launch the desktop app).
2. Pull a Gemma 3 model. **`gemma3:latest` (the `4b` tag, 3.3GB) is the default and what's been validated
   against this project's evals** — it's fast enough for interactive use on Apple Silicon and doesn't
   require a large download:

    ```shell
    ollama pull gemma3
    ```

   Larger sizes (`gemma3:12b`, 8.1GB; `gemma3:27b`, 17GB) offer better quality/reasoning at the cost of
   slower responses and a much bigger download — set `OLLAMA_MODEL` accordingly if you have the memory and
   bandwidth for one and want to compare results. Only `gemma3:latest` (4B) has actually been validated
   against `linkedin_invitation_cases.yaml` in this project so far; larger sizes are untested here.

3. Choose the backend with the `--model-backend` flag (or the `MODEL_BACKEND` env var in `.env`):

    | Value | Behavior |
    |---|---|
    | `ollama` (default) | Uses the local Ollama model only. No Azure credentials required. |
    | `openai` | Uses the standard OpenAI API with `OPENAI_API_KEY` and `OPENAI_MODEL`. |
    | `azure` | Uses Azure OpenAI only, exactly as configured in [Configuring Azure AI models](#configuring-azure-ai-models). |
    | `fallback` | Tries Ollama first, and falls back to Azure OpenAI if the local model call fails (e.g. Ollama isn't running). **Still requires Azure credentials to be configured** (as in `azure` mode above) since both models are constructed at startup. |

    ```shell
    uv run python invitations_manager.py --model-backend ollama
    uv run python inbox_manager.py --model-backend openai
    ```

   To change the default without passing a flag every time, set in `.env`:

    ```shell
    MODEL_BACKEND=ollama
    OLLAMA_BASE_URL=http://localhost:11434/v1
    OLLAMA_MODEL=gemma3:latest
    ```

   Every LLM call (both scripts, all backends) is bounded so a model that gets stuck generating can't
   stall the run. Override the defaults in `.env` if needed:

    | Variable | Default | Effect |
    |---|---|---|
    | `LLM_MAX_TOKENS` | `512` | Maximum output tokens per call. |
    | `LLM_TIMEOUT_SECONDS` | `60` | Per-request timeout. The OpenAI SDK retries timeouts twice, so the worst case is ~3× this. |

   When a call fails, `inbox_manager.py` gives that conversation an urgency score of 1, and
   `invitations_manager.py` leaves that invitation pending and moves on.

**Known caveat:** Gemma 3's structured-output reliability through Ollama's OpenAI-compatible API is not
as consistent as larger frontier models — in local testing against `linkedin_invitation_cases.yaml`
(via `uv run python evals.py`), correctness scores varied between 80–100% across four separate runs with
`gemma3:latest` (4B), with no malformed/unparseable outputs observed in any run. Validate against your own
eval cases before relying on the `ollama` or `fallback` backend for unattended runs. See
[`docs/reports/local-model-serving-for-gemma3.md`](docs/reports/local-model-serving-for-gemma3.md) for the
full research behind this choice (framework comparison, benchmarks, licensing).

## Running the invitation manager

You can run the LinkedIn agent by executing the `invitations_manager.py` script. The agent analyzes invitations and queues each proposed Accept or Ignore action for mandatory human review. This command never clicks either LinkedIn action.

```shell
uv run python invitations_manager.py --num-to-process 10
```

Available flags:

* `--num-to-process` (default `10`): number of invitations to process before stopping.
* `--record-eval-cases`: append each processed invitation as a new case to `linkedin_invitation_cases.yaml`, for later use with `evals.py`.
* `--headless`: run the browser without a visible window.
* `--apply-inbox-decisions`: apply accept/ignore decisions a human already made in Agent Inbox.
* `--model-backend` (`ollama` | `openai` | `azure` | `fallback`, default: `MODEL_BACKEND` env var, itself defaulting to `ollama`): which model backend to use. See [Configuring OpenAI models](#configuring-openai-models) and [Configuring Ollama Models](#configuring-ollama-models).

On first run (or whenever the saved session expires), a browser window opens to `linkedin.com/login` and waits for you to log in manually; the resulting session is cached to `playwright/.auth/state.json` so future runs skip the login step.

## Human review with Agent Inbox

Every proposed invitation action and reply-worthy message must be reviewed by a human in [Agent Inbox](https://github.com/langchain-ai/agent-inbox), included as a git submodule in `agent-inbox/`. `review_graph.py` defines two LangGraph graphs that pause with an `interrupt`: `invitation_review` (**Accept** / **Ignore**) and `message_review` (**Accept** the suggested reply, **Edit** it, or **Ignore**). Queue failures stop the proposal workflow rather than falling back to a LinkedIn action.

1. Fetch the UI and install it (requires Node.js and yarn): `git submodule update --init && git -C agent-inbox apply ../patches/agent-inbox-fixes.patch && (cd agent-inbox && yarn install)`. The patch fixes nested `<p>` hydration errors, applies styling outside `react-markdown` instead of passing its removed `className` prop, and makes a scheme-less Deployment URL (e.g. `localhost:2024`) default to `http://` instead of throwing "Invalid URL". Skip the apply if already applied.
2. Start the LangGraph server: `uv run langgraph dev --no-browser` (serves `http://localhost:2024`)
3. Start the UI: `cd agent-inbox && yarn dev` and open <http://localhost:3000>. In **Settings**, enter your LangSmith API key, then **Add Inbox** with Deployment URL `http://localhost:2024` and Assistant/Graph ID `invitation_review`. Add a second inbox with Graph ID `message_review` for messages.
4. Analyze invitations and queue every proposed Accept or Ignore action: `uv run python invitations_manager.py --num-to-process 10`
5. Resolve them in the inbox, then apply the decisions to LinkedIn: `uv run python invitations_manager.py --apply-inbox-decisions`
6. Messages: `uv run python inbox_manager.py --num-messages 20 [--min-urgency 4]` queues every conversation with an actionable suggested reply at or above the urgency threshold. After reviewing them, `uv run python inbox_manager.py --apply-inbox-decisions` opens the approved conversations and prints the approved reply for you to paste. **Nothing is ever sent automatically.**

Newsletter invitations are left pending because the current scraper cannot reliably identify both actions for those non-profile cards. They are never ignored automatically.

Environment variables (read from the environment or `.env`, never logged): `LANGGRAPH_URL` (default `http://localhost:2024`) and `LANGSMITH_API_KEY` (falls back to `LANGSMITH_PERSONAL_ACCESS_TOKEN`; a local `langgraph dev` server doesn't check it).

## Running the inbox manager

`inbox_manager.py` is a separate script that scans your recent LinkedIn conversations, uses an LLM to score each thread's reply urgency (1-10), queues actionable reply proposals for mandatory review, and opens the highest-priority conversation. Opening a conversation is read-only; the script never sends a message.

```shell
uv run python inbox_manager.py --num-messages 20
```

Available flags:

* `--num-messages` (default `20`): number of recent conversations to analyze.
* `--min-urgency` (default `4`): minimum urgency score (1-10) for an actionable reply proposal to be queued in Agent Inbox.
* `--apply-inbox-decisions`: skip ranking; open conversations approved in Agent Inbox and print the approved reply. Nothing is sent.
* `--model-backend` (`ollama` | `openai` | `azure` | `fallback`, default: `MODEL_BACKEND` env var, itself defaulting to `ollama`): which model backend to use. See [Configuring OpenAI models](#configuring-openai-models) and [Configuring Ollama Models](#configuring-ollama-models).

It reuses the same `playwright/.auth/state.json` login session as the invitation manager. Unlike `invitations_manager.py`, it does not currently support `--headless`.

> **Note:** `inbox_manager.py` builds its Azure OpenAI client differently than `invitations_manager.py` (different base URL construction, model class, and credential type). See [Architecture](#architecture) for details.

## Running evaluations

This project includes evaluations using Pydantic-AI evals to measure the agent's performance. You can run the evaluations by executing the `evals.py` script.

`evals.py` imports the `agent` object directly from `invitations_manager.py`, so it evaluates whichever backend `MODEL_BACKEND` resolves to at import time (`ollama` by default — see [Configuring Ollama Models](#configuring-ollama-models)). To evaluate against OpenAI or Azure OpenAI instead, set the corresponding backend before running:

```shell
MODEL_BACKEND=openai uv run python evals.py
MODEL_BACKEND=azure uv run python evals.py
```

Recorded/appended cases (via `invitations_manager.py --record-eval-cases`) include a `metadata.model_name` field identifying which model actually produced each decision (useful when running in `fallback` mode, since the local model may have failed over to Azure for a given call).

## Cost estimate

On average, each LinkedIn invitation processed by the agent requires approximately 200 tokens. If the agent decides it needs to open the full profile page to gather more information, it requires an additional 400 tokens on average.

OpenAI and Azure OpenAI cost depends on the selected model and usage. See the [OpenAI API pricing page](https://openai.com/api/pricing/) and [Azure OpenAI pricing page](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/).

## Architecture

For a deeper dive into each stack's purpose, modules, data layer, and known tech debt, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Resources

* [Video: Live demo of the agent](https://www.youtube.com/live/-OsgE9yBkFE)
* [Pydantic AI Documentation](https://ai.pydantic.dev/)
* [Playwright Documentation](https://playwright.dev/python/)
* [OpenAI Function Calling Documentation](https://platform.openai.com/docs/guides/function-calling?api-mode=chat)
