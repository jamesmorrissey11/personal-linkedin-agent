"""Model-backend construction in linkedin_agent.llm, including the two preserved Azure client variants."""

from types import SimpleNamespace

import pytest

from linkedin_agent import inbox, invitations, llm


class FakeAsyncOpenAI:
    instances: list["FakeAsyncOpenAI"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        FakeAsyncOpenAI.instances.append(self)


@pytest.fixture
def fake_openai(monkeypatch):
    FakeAsyncOpenAI.instances = []
    monkeypatch.setattr(llm, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(llm, "OpenAIProvider", lambda *, openai_client: SimpleNamespace(client=openai_client))
    monkeypatch.setattr(llm, "OpenAIChatModel", lambda model_name, *, provider: SimpleNamespace(model_name=model_name, provider=provider))
    return FakeAsyncOpenAI


def test_build_openai_model_requires_api_key(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        llm.build_openai_model()


def test_build_openai_model_uses_api_key_and_configured_model(monkeypatch, fake_openai):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-model")

    model = llm.build_openai_model()

    assert model.model_name == "gpt-test-model"
    assert fake_openai.instances[0].kwargs == {"api_key": "test-openai-key"}
    assert model.provider.client is fake_openai.instances[0]


def test_build_openai_model_constructs_real_pydantic_model_without_network(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-test-model")

    assert llm.build_openai_model().model_name == "gpt-test-model"


def test_build_model_selects_openai_without_changing_fallback(monkeypatch):
    openai_model = SimpleNamespace(model_name="openai-test")
    fallback_model = SimpleNamespace(model_name="fallback-test")
    monkeypatch.setattr(llm, "build_openai_model", lambda: openai_model)
    monkeypatch.setattr(llm, "FallbackModel", lambda ollama, azure: fallback_model)
    monkeypatch.setattr(llm, "build_ollama_model", lambda: SimpleNamespace(model_name="ollama-test"))
    monkeypatch.setattr(llm, "build_azure_model", lambda variant: SimpleNamespace(model_name="azure-test"))

    assert llm.build_model("openai", azure_variant="invitations") is openai_model
    assert llm.build_model("fallback", azure_variant="invitations") is fallback_model


def test_unknown_backend_error_lists_openai():
    with pytest.raises(ValueError, match="'openai'"):
        llm.build_model("unknown", azure_variant="invitations")


def test_env_is_read_when_building_not_at_import(monkeypatch):
    monkeypatch.setenv("LLM_MAX_TOKENS", "77")
    monkeypatch.setenv("MODEL_BACKEND", "openai")

    assert llm.model_settings()["max_tokens"] == 77
    assert llm.default_model_backend() == "openai"


def test_invitations_azure_variant_uses_openai_v1_and_developer_cli_credential(monkeypatch, fake_openai):
    credentials = []
    monkeypatch.setenv("AZURE_TENANT_ID", "tenant")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "deployment")
    monkeypatch.setattr(llm.azure.identity.aio, "AzureDeveloperCliCredential", lambda tenant_id: credentials.append(("cli", tenant_id)) or "cli-credential")
    monkeypatch.setattr(llm.azure.identity.aio, "get_bearer_token_provider", lambda credential, scope: ("async-provider", credential, scope))

    model = llm.build_azure_model("invitations")

    assert model.model_name == "deployment"
    assert fake_openai.instances[0].kwargs == {"base_url": "https://example.openai.azure.com/openai/v1", "api_key": ("async-provider", "cli-credential", llm.AZURE_SCOPE)}
    assert credentials == [("cli", "tenant")]


def test_inbox_azure_variant_uses_bare_endpoint_and_default_credential(monkeypatch, fake_openai):
    monkeypatch.delenv("AZURE_TENANT_ID", raising=False)
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_CHAT_DEPLOYMENT", "deployment")
    monkeypatch.setattr(llm.azure.identity, "DefaultAzureCredential", lambda: "default-credential")
    monkeypatch.setattr(llm.azure.identity, "get_bearer_token_provider", lambda credential, scope: lambda: f"token-from-{credential}")

    model = llm.build_azure_model("inbox")

    kwargs = fake_openai.instances[0].kwargs
    assert model.model_name == "deployment"
    assert kwargs["base_url"] == "https://example.openai.azure.com"
    from tests.async_helpers import run_async_test

    assert run_async_test(kwargs["api_key"]) == "token-from-default-credential"


@pytest.mark.parametrize(("variant", "missing"), [("invitations", "AZURE_TENANT_ID"), ("inbox", "AZURE_OPENAI_ENDPOINT")])
def test_azure_variants_report_their_missing_env(monkeypatch, variant, missing):
    for name in ("AZURE_TENANT_ID", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_CHAT_DEPLOYMENT"):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match=missing):
        llm.build_azure_model(variant)


def test_unknown_azure_variant_is_rejected():
    with pytest.raises(ValueError, match="'invitations' or 'inbox'"):
        llm.build_azure_model("other")


@pytest.mark.parametrize(("workflow", "expected_variant"), [(invitations, "invitations"), (inbox, "inbox")])
def test_each_workflow_keeps_its_own_azure_variant(monkeypatch, workflow, expected_variant):
    calls = []
    monkeypatch.setattr(workflow, "build_model", lambda backend, azure_variant: calls.append((backend, azure_variant)) or SimpleNamespace(model_name="m"))

    if workflow is invitations:
        monkeypatch.setattr(invitations, "Agent", lambda *args, **kwargs: SimpleNamespace())
        workflow.configure("azure")
    else:
        monkeypatch.setattr(inbox, "_model", None)
        workflow.configure("azure")

    assert calls == [("azure", expected_variant)]
