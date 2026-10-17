"""Every test gets its own runtime folder, so no test can read or write the real LinkedIn session or inbox data."""

import pytest


@pytest.fixture(autouse=True)
def isolated_runtime_state(monkeypatch, tmp_path_factory):
    monkeypatch.setenv("LINKEDIN_AGENT_HOME", str(tmp_path_factory.mktemp("linkedin-agent-home")))
