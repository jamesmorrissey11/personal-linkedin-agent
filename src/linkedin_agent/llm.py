"""Model backends for the LLM workflows: Ollama (default), OpenAI, Azure OpenAI, or Ollama with Azure fallback.

Environment variables are read when a model is built, never at import. Choose a backend with the
MODEL_BACKEND env var or the CLI's --model-backend flag.

The two workflows deliberately use different Azure OpenAI client setups (see
`.github/instructions/python.instructions.md`). They are kept side by side behind the explicit
`azure_variant` parameter rather than unified:

- "invitations": `AZURE_OPENAI_ENDPOINT + "/openai/v1"` with an async `AzureDeveloperCliCredential`
  (the known-working pattern; use it for any new workflow).
- "inbox": the bare `AZURE_OPENAI_ENDPOINT` with a sync `DefaultAzureCredential`.
"""

import logging
import os
from typing import Literal

import azure.identity
import azure.identity.aio
from openai import AsyncOpenAI
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings

from linkedin_agent.runtime import SetupError, check_url

logger = logging.getLogger("llm")
logger.setLevel(logging.INFO)

MODEL_BACKENDS = ("ollama", "openai", "azure", "fallback")
AzureVariant = Literal["invitations", "inbox"]
AZURE_SCOPE = "https://cognitiveservices.azure.com/.default"


def default_model_backend() -> str:
    return os.environ.get("MODEL_BACKEND", "ollama")


def model_settings() -> ModelSettings:
    """Bound every LLM call so a small local model stuck generating can't stall the run.

    Ollama runs with --context-shift, so it never hits the context limit. The OpenAI SDK retries
    timeouts twice, so the worst case per call is roughly 3x LLM_TIMEOUT_SECONDS.
    """
    return ModelSettings(
        max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "512")),
        timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
    )


def build_ollama_model() -> OllamaModel:
    """Build the local Ollama model. Requires `ollama serve` running locally with OLLAMA_MODEL pulled."""
    return OllamaModel(
        os.environ.get("OLLAMA_MODEL", "gemma3:latest"),
        provider=OllamaProvider(base_url=ollama_base_url()),
    )


def build_openai_model() -> OpenAIChatModel:
    """Build a standard OpenAI API model using OPENAI_API_KEY."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise SetupError("Missing required OPENAI_API_KEY for --model-backend openai.", "Set it in .env, or choose another backend with --model-backend.")
    openai_client = AsyncOpenAI(api_key=api_key)
    return OpenAIChatModel(os.environ.get("OPENAI_MODEL", "gpt-4.1-mini"), provider=OpenAIProvider(openai_client=openai_client))


def _require_env(names: list[str]) -> None:
    missing_vars = [var for var in names if not os.environ.get(var)]
    if missing_vars:
        raise SetupError(f"Missing required Azure OpenAI environment variable(s) for --model-backend azure/fallback: {', '.join(missing_vars)}.", "Set them in .env (`azd provision` in deploy/azure writes them), or use --model-backend ollama (the default) to run without Azure credentials.")


def _build_invitations_azure_client() -> AsyncOpenAI:
    _require_env(["AZURE_TENANT_ID", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_CHAT_DEPLOYMENT"])
    token_provider = azure.identity.aio.get_bearer_token_provider(
        azure.identity.aio.AzureDeveloperCliCredential(tenant_id=os.environ["AZURE_TENANT_ID"]),
        AZURE_SCOPE,
    )
    return AsyncOpenAI(base_url=os.environ["AZURE_OPENAI_ENDPOINT"] + "/openai/v1", api_key=token_provider)


def _build_inbox_azure_client() -> AsyncOpenAI:
    _require_env(["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_CHAT_DEPLOYMENT"])
    token_provider = azure.identity.get_bearer_token_provider(azure.identity.DefaultAzureCredential(), AZURE_SCOPE)

    async def async_token_provider() -> str:
        # AsyncOpenAI expects an async callable for `api_key`, but this variant uses a sync credential,
        # whose token provider is sync. Wrap it rather than switching credential types.
        return token_provider()

    return AsyncOpenAI(base_url=os.environ["AZURE_OPENAI_ENDPOINT"], api_key=async_token_provider)


def ollama_base_url() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")


def check_backend(backend: str) -> None:
    """Fail fast when the local Ollama backend isn't running. Hosted backends are checked by their settings at
    build time, and "fallback" is left alone because it falls back to Azure when Ollama is down."""
    if backend == "ollama":
        url = ollama_base_url()
        check_url(f"{url.rstrip('/')}/models", f"Ollama isn't reachable at {url}.", "Start it with `ollama serve` (and `ollama pull` the model), or choose another backend with --model-backend openai.")


def build_azure_model(azure_variant: AzureVariant) -> OpenAIChatModel:
    """Build the Azure OpenAI model with the given workflow's client setup (see the module docstring)."""
    if azure_variant == "invitations":
        azure_client = _build_invitations_azure_client()
    elif azure_variant == "inbox":
        azure_client = _build_inbox_azure_client()
    else:
        raise ValueError(f"Unknown Azure client variant: {azure_variant!r}. Expected 'invitations' or 'inbox'.")
    return OpenAIChatModel(os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"], provider=OpenAIProvider(openai_client=azure_client))


def build_model(backend: str, azure_variant: AzureVariant):
    """Build the Pydantic AI model for the given backend.

    OpenAI and Azure credentials are read only when their corresponding backend is selected. Note that
    "fallback" constructs the Azure model eagerly (FallbackModel requires both models up front), so
    Azure credentials must still be present at startup even though Ollama is tried first at request time.
    """
    if backend == "ollama":
        chosen_model = build_ollama_model()
    elif backend == "openai":
        chosen_model = build_openai_model()
    elif backend == "azure":
        chosen_model = build_azure_model(azure_variant)
    elif backend == "fallback":
        chosen_model = FallbackModel(build_ollama_model(), build_azure_model(azure_variant))
    else:
        raise ValueError(f"Unknown model backend: {backend!r}. Expected 'ollama', 'openai', 'azure', or 'fallback'.")
    logger.info("Using model backend=%s (model_name=%s)", backend, chosen_model.model_name)
    return chosen_model
