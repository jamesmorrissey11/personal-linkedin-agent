from types import SimpleNamespace

import pytest

import inbox_manager
import invitations_manager


@pytest.mark.parametrize("manager", [invitations_manager, inbox_manager])
def test_build_openai_model_requires_api_key(monkeypatch, manager):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        manager.build_openai_model()


@pytest.mark.parametrize("manager", [invitations_manager, inbox_manager])
def test_build_openai_model_uses_api_key_and_configured_model(monkeypatch, manager):
    captured = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured["client_kwargs"] = kwargs

    class FakeProvider:
        def __init__(self, *, openai_client):
            captured["provider_client"] = openai_client

    class FakeModel:
        def __init__(self, model_name, *, provider):
            self.model_name = model_name
            captured["model_name"] = model_name
            captured["model_provider"] = provider

    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(manager, "OPENAI_MODEL", "gpt-test-model")
    monkeypatch.setattr(manager, "AsyncOpenAI", FakeAsyncOpenAI)
    monkeypatch.setattr(manager, "OpenAIProvider", FakeProvider)
    monkeypatch.setattr(manager, "OpenAIChatModel", FakeModel)

    model = manager.build_openai_model()

    assert model.model_name == "gpt-test-model"
    assert captured["client_kwargs"] == {"api_key": "test-openai-key"}
    assert captured["provider_client"].__class__ is FakeAsyncOpenAI
    assert captured["model_name"] == "gpt-test-model"
    assert captured["model_provider"].__class__ is FakeProvider


@pytest.mark.parametrize("manager", [invitations_manager, inbox_manager])
def test_build_openai_model_constructs_real_pydantic_model_without_network(monkeypatch, manager):
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setattr(manager, "OPENAI_MODEL", "gpt-test-model")

    model = manager.build_openai_model()

    assert model.model_name == "gpt-test-model"


@pytest.mark.parametrize("manager", [invitations_manager, inbox_manager])
def test_build_model_selects_openai_without_changing_fallback(monkeypatch, manager):
    openai_model = SimpleNamespace(model_name="openai-test")
    fallback_model = SimpleNamespace(model_name="fallback-test")
    monkeypatch.setattr(manager, "build_openai_model", lambda: openai_model)
    monkeypatch.setattr(manager, "FallbackModel", lambda ollama, azure: fallback_model)
    monkeypatch.setattr(manager, "build_ollama_model", lambda: SimpleNamespace(model_name="ollama-test"))
    monkeypatch.setattr(manager, "build_azure_model", lambda: SimpleNamespace(model_name="azure-test"))

    assert manager.build_model("openai") is openai_model
    assert manager.build_model("fallback") is fallback_model


@pytest.mark.parametrize("manager", [invitations_manager, inbox_manager])
def test_unknown_backend_error_lists_openai(manager):
    with pytest.raises(ValueError, match="'openai'"):
        manager.build_model("unknown")
