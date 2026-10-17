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
    automatically, so manual activation is not required. It also installs this project's `linkedin_agent`
    package (in editable mode, from `src/`) and its `linkedin-agent` command, so `uv run linkedin-agent --help` works.

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
uv run linkedin-agent invitations --model-backend openai
uv run linkedin-agent inbox --model-backend openai
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
   against `evals/invitation_cases.yaml` in this project so far; larger sizes are untested here.

3. Choose the backend with the `--model-backend` flag (or the `MODEL_BACKEND` env var in `.env`):

    | Value | Behavior |
    |---|---|
    | `ollama` (default) | Uses the local Ollama model only. No Azure credentials required. |
    | `openai` | Uses the standard OpenAI API with `OPENAI_API_KEY` and `OPENAI_MODEL`. |
    | `azure` | Uses Azure OpenAI only, exactly as configured in [Configuring Azure AI models](#configuring-azure-ai-models). |
    | `fallback` | Tries Ollama first, and falls back to Azure OpenAI if the local model call fails (e.g. Ollama isn't running). **Still requires Azure credentials to be configured** (as in `azure` mode above) since both models are constructed at startup. |

    ```shell
    uv run linkedin-agent invitations --model-backend ollama
    uv run linkedin-agent inbox --model-backend openai
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

   When a call fails, the inbox workflow still queues that conversation, labeled "Couldn't score", and
   the invitation workflow still queues that invitation, labeled "Needs your judgment".

**Known caveat:** Gemma 3's structured-output reliability through Ollama's OpenAI-compatible API is not
as consistent as larger frontier models — in local testing against `evals/invitation_cases.yaml`
(via `uv run python -m evals.run`), correctness scores varied between 80–100% across four separate runs with
`gemma3:latest` (4B), with no malformed/unparseable outputs observed in any run. Validate against your own
eval cases before relying on the `ollama` or `fallback` backend for unattended runs. See
[`docs/reports/local-model-serving-for-gemma3.md`](docs/reports/local-model-serving-for-gemma3.md) for the
full research behind this choice (framework comparison, benchmarks, licensing).

## Running the invitation manager

You can run the LinkedIn agent with the `linkedin-agent invitations` command. The agent analyzes invitations and queues each proposed Accept or Ignore action for mandatory human review. This command never clicks either LinkedIn action.

```shell
uv run linkedin-agent invitations
```

Every new invitation is queued, including ones the agent was undecided about or whose LLM call failed (labelled **Needs your judgment**). Invitations that already have a review are skipped without an LLM call, and scanning stops once it reaches already-known invitations.

Available flags:

* `--num-to-process` (default `100`): safety cap on *new* invitations queued per run (known ones don't count). The run report says when the cap was hit.
* `--cleanup-stale`: close pending reviews for invitations no longer on LinkedIn, only after a full, non-empty scan.
* `--record-eval-cases`: append each processed invitation as a new case to `evals/invitation_cases.yaml`, for later use with the evals (`uv run python -m evals.run`).
* `--headless`: run the browser without a visible window.
* `--model-backend` (`ollama` | `openai` | `azure` | `fallback`, default: `MODEL_BACKEND` env var, itself defaulting to `ollama`): which model backend to use. See [Configuring OpenAI models](#configuring-openai-models) and [Configuring Ollama Models](#configuring-ollama-models).

On first run (or whenever the saved session expires), a browser window opens to `linkedin.com/login` and waits for you to log in manually; the resulting session is cached to `playwright/.auth/state.json` so future runs skip the login step.

## Human review with Agent Inbox

Every proposed invitation action and reply-worthy message must be reviewed by a human in [Agent Inbox](https://github.com/langchain-ai/agent-inbox), included as a git submodule in `agent-inbox/`. `src/linkedin_agent/review/graphs.py` defines two LangGraph graphs that pause with an `interrupt`: `invitation_review` (**Accept** / **Ignore**) and `message_review` (**Accept** the suggested reply, **Edit** it, or **Ignore**). Your decision is the action: the graph immediately accepts or ignores the invitation, sends the exact submitted reply, or archives the ignored conversation. A failed or stale action returns to Agent Inbox with a visible note instead of silently closing.

1. Fetch the UI and install it (requires Node.js and yarn): `git submodule update --init && git -C agent-inbox apply ../patches/agent-inbox-fixes.patch && (cd agent-inbox && yarn install)`. The patch fixes nested `<p>` hydration errors, applies styling outside `react-markdown` instead of passing its removed `className` prop, and makes a scheme-less Deployment URL (e.g. `localhost:2024`) default to `http://` instead of throwing "Invalid URL". Skip the apply if already applied.
2. Start the LangGraph server: `uv run langgraph dev --no-browser --no-reload` (serves `http://localhost:2024`; disabling reload prevents an edit from interrupting an action)
3. Start the UI: `cd agent-inbox && yarn dev` and open <http://localhost:3000>. In **Settings**, enter your LangSmith API key, then **Add Inbox** with Deployment URL `http://localhost:2024` and Assistant/Graph ID `invitation_review`. Add a second inbox with Graph ID `message_review` for messages.
4. Analyze invitations and queue every one for review: `uv run linkedin-agent invitations`
5. Resolve an invitation in Agent Inbox. **Accept** or **Ignore** acts on LinkedIn immediately and closes the item only after the action succeeds.
6. Messages: `uv run linkedin-agent inbox [--min-urgency 4]` queues every conversation where the other person spoke last. Urgency is a label (`Low urgency`, `Couldn't score`), not a filter. **Accept** sends the suggested reply, **Edit** sends the exact edited text, and **Ignore** archives the conversation. Accept is hidden when there is no non-empty suggestion.

Newsletter invitations are left pending because the current scraper cannot reliably identify both actions for those non-profile cards. They are never ignored automatically.

Environment variables (read from the environment or `.env`, never logged): `LANGGRAPH_URL` (default `http://localhost:2024`) and `LANGSMITH_API_KEY` (falls back to `LANGSMITH_PERSONAL_ACCESS_TOKEN`; a local `langgraph dev` server doesn't check it).

## No LinkedIn action happens without human approval

**Nothing is accepted, ignored, sent, or archived on LinkedIn unless you chose it for that one item in Agent Inbox. The LLM only suggests.** Deleting, reporting, blocking, leaving, recalling, or bulk-approving remains unsupported. `src/linkedin_agent/linkedin/guard.py` enforces this in layers:

1. **Sync contexts are read-only:** the managers and daily job use the default-deny network and composer guards, including blocked read receipts and presence writes.
2. **Action contexts are single-use:** `src/linkedin_agent/linkedin/actions.py` opens one guarded context with an `ApprovedAction` for only the chosen send, archive, accept, or ignore operation.
3. **Exact-text sends:** the action fills the exact submitted reply, verifies the composer contents, allows one send request, and confirms the sent text before closing.
4. **Stale-state checks:** a new incoming message or a reply already made on LinkedIn stops the action and returns the item for a fresh decision. A repeated action never blindly replays.
5. **No LLM actuators:** the agents expose no tools; only `review/graphs.py` calls the action functions after an Agent Inbox interrupt resumes.
6. **CI architecture tests:** `tests/unit/test_no_message_writes.py` limits composer/write selectors to the action module and verifies every action context and guarded click carries an approval.

## Daily unattended workflow

`linkedin-agent daily` is sync-only. It runs in this order: (1) recover interrupted review actions and retire legacy pre-live-action decisions, (2) close invitations and conversations already handled directly on LinkedIn, (3) propose new invitations and messages, and (4) post a summary notification. It never accepts, ignores, sends, or archives anything. The rule is **fail open**: when unsure, an item stays queued rather than being hidden.

```shell
uv run linkedin-agent daily --headless
```

* Exit codes: `0` success, `1` health failure (e.g. a scrape returned zero items, so nothing is closed), `2` LinkedIn login needed (a macOS notification is posted instead of waiting). Logs go to `logs/daily_run.log`.
* Run reports show new / already queued / superseded counts, recovered interrupted actions, and retired legacy decisions.
* Stale items are closed as `superseded` (never deleted): an invitation gone from a full, non-empty list, a conversation whose latest message is exactly yours, a conversation archived on LinkedIn, or a conversation replaced by a newer incoming message. Ambiguous cases are kept.
* A new incoming message after a reply or archive is queued again because deduplication only considers currently pending reviews.
* Schedule it with launchd (daily 06:30 sync run and a keep-alive `langgraph dev --no-reload` server): see [`scheduling/README.md`](scheduling/README.md).

## Running the inbox manager

`linkedin-agent inbox` is a separate command that scans your LinkedIn conversations until it reaches ones already handled, uses an LLM to score each new thread's reply urgency (1-10), queues every conversation where someone else spoke last for mandatory review, and opens the highest-priority conversation (interactive runs only). Opening a conversation is read-only; the script never sends a message.

```shell
uv run linkedin-agent inbox
```

Available flags:

* `--num-messages` (default `100`): safety cap on conversations scanned per run.
* `--min-urgency` (default `4`): conversations scoring below this get a `Low urgency` label; they are still queued.
* `--headless`: run the browser without a visible window.
* `--cleanup-only`: no LLM; close pending reviews for conversations you replied to or archived directly on LinkedIn.
* `--model-backend` (`ollama` | `openai` | `azure` | `fallback`, default: `MODEL_BACKEND` env var, itself defaulting to `ollama`): which model backend to use. See [Configuring OpenAI models](#configuring-openai-models) and [Configuring Ollama Models](#configuring-ollama-models).

It reuses the same `playwright/.auth/state.json` login session as the invitation manager.

> **Note:** the inbox workflow builds its Azure OpenAI client differently than the invitation workflow (different base URL construction and credential type). Both variants are kept, deliberately, in `src/linkedin_agent/llm.py`. See [Architecture](#architecture) for details.

## Running evaluations

This project includes evaluations using Pydantic-AI evals to measure the agent's performance. You can run the evaluations with `uv run python -m evals.run`.

The evals use the invitation workflow's decision agent, so they evaluate whichever backend `MODEL_BACKEND` resolves to (`ollama` by default — see [Configuring Ollama Models](#configuring-ollama-models)). To evaluate against OpenAI or Azure OpenAI instead, set the corresponding backend before running:

```shell
MODEL_BACKEND=openai uv run python -m evals.run
MODEL_BACKEND=azure uv run python -m evals.run
```

Recorded/appended cases (via `linkedin-agent invitations --record-eval-cases`) include a `metadata.model_name` field identifying which model actually produced each decision (useful when running in `fallback` mode, since the local model may have failed over to Azure for a given call).

## Cost estimate

On average, each LinkedIn invitation processed by the agent requires approximately 200 tokens. If the agent decides it needs to open the full profile page to gather more information, it requires an additional 400 tokens on average.

OpenAI and Azure OpenAI cost depends on the selected model and usage. See the [OpenAI API pricing page](https://openai.com/api/pricing/) and [Azure OpenAI pricing page](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/).

## Architecture

All Python code is one package, `src/linkedin_agent/`, run through `uv run linkedin-agent <command>`:

```text
src/linkedin_agent/
  cli.py          # `linkedin-agent invitations | inbox | daily`
  invitations.py  # invitation workflow: agent, prompt, propose and sync
  inbox.py        # inbox workflow: urgency agent, prompt, propose and sync
  daily.py        # the unattended daily sync
  llm.py          # model backends (Ollama, OpenAI, Azure OpenAI, fallback)
  runtime.py      # shared errors, run counts, logging setup, notifications
  linkedin/       # Playwright and LinkedIn: models, session, pages, guard, actions
  review/         # LangGraph and Agent Inbox: graphs, queue
evals/            # developer-only evals: `uv run python -m evals.run`
```

For a deeper dive into each stack's purpose, modules, data layer, and known tech debt, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Resources

* [Video: Live demo of the agent](https://www.youtube.com/live/-OsgE9yBkFE)
* [Pydantic AI Documentation](https://ai.pydantic.dev/)
* [Playwright Documentation](https://playwright.dev/python/)
* [OpenAI Function Calling Documentation](https://platform.openai.com/docs/guides/function-calling?api-mode=chat)
