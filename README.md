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

    * [Python 3.10+](https://www.python.org/downloads/)
    * Git

2. Clone the repository:

    ```shell
    git clone https://github.com/jamesmorrissey11/personal-linkedin-agent
    cd personal-linkedin-agent
    ```

3. Set up a virtual environment:

    ```shell
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

4. Install the requirements:

    ```shell
    pip install -r requirements.txt
    ```

5. Install the Playwright browser binaries (required once per environment; the `playwright` pip package alone does not include them):

    ```shell
    playwright install chromium
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

## Configuring Ollama Models

#TODO: Add support for Ollama models run on Mac as replacement for Azure OpenAI  

## Running the invitation manager

You can run the LinkedIn agent by executing the `invitations_manager.py` script. The agent will process LinkedIn invitations based on the decision logic defined in the code.

```shell
python invitations_manager.py --num-to-process 10
```

Available flags:

* `--num-to-process` (default `10`): number of invitations to process before stopping.
* `--record-eval-cases`: append each processed invitation as a new case to `linkedin_invitation_cases.yaml`, for later use with `evals.py`.
* `--headless`: run the browser without a visible window.

On first run (or whenever the saved session expires), a browser window opens to `linkedin.com/login` and waits for you to log in manually; the resulting session is cached to `playwright/.auth/state.json` so future runs skip the login step.

## Running the inbox manager

`inbox_manager.py` is a separate script that scans your recent LinkedIn conversations, uses an LLM to score each thread's reply urgency (1-10), and opens the highest-priority conversation.

```shell
python inbox_manager.py --num-messages 20
```

Available flags:

* `--num-messages` (default `20`): number of recent conversations to analyze.

It reuses the same `playwright/.auth/state.json` login session as the invitation manager. Unlike `invitations_manager.py`, it does not currently support `--headless`.

> **Note:** `inbox_manager.py` builds its Azure OpenAI client differently than `invitations_manager.py` (different base URL construction, model class, and credential type). See [Architecture](#architecture) for details.

## Running evaluations

This project includes evaluations using Pydantic-AI evals to measure the agent's performance. You can run the evaluations by executing the `evals.py` script.

## Cost estimate

On average, each LinkedIn invitation processed by the agent requires approximately 200 tokens. If the agent decides it needs to open the full profile page to gather more information, it requires an additional 400 tokens on average.

Azure OpenAI cost depends on the deployed model and usage. See the [Azure OpenAI pricing page](https://azure.microsoft.com/pricing/details/cognitive-services/openai-service/).

## Architecture

For a deeper dive into each stack's purpose, modules, data layer, and known tech debt, see [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Resources

* [Video: Live demo of the agent](https://www.youtube.com/live/-OsgE9yBkFE)
* [Pydantic AI Documentation](https://ai.pydantic.dev/)
* [Playwright Documentation](https://playwright.dev/python/)
* [OpenAI Function Calling Documentation](https://platform.openai.com/docs/guides/function-calling?api-mode=chat)
