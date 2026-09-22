"""Non-Playwright pytest backfill for invitations_manager.py's LLM-decision logic seams:
InvitationDecision/Invitation model validation, run_and_log_agent's YAML case-logging
behavior (with the real Agent.run mocked out - no Azure OpenAI calls), and a schema-shape
check of linkedin_invitation_cases.yaml.

run_and_log_agent() unconditionally appends to a hardcoded relative path
("linkedin_invitation_cases.yaml"). To avoid polluting the repo's real append-only eval
dataset, the YAML-writing test uses monkeypatch.chdir(tmp_path) so the relative path
resolves inside a temporary directory instead - this is a test-only technique and does
not change production code.

The async run_and_log_agent() call is driven via asyncio.run() from a plain (sync) test
function rather than an async def test with pytest-asyncio/anyio, to avoid adding a
dependency not required for mocking. See tests/conftest.py for why these asyncio.run()
tests are ordered before pytest-playwright's sync `page`-fixture tests.
"""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import yaml
from pydantic import ValidationError

import invitations_manager
from invitations_manager import Invitation, InvitationAction, InvitationDecision, run_and_log_agent


def test_invitation_decision_accepts_valid_action():
    decision = InvitationDecision(action=InvitationAction.ACCEPT, reason="Works at Microsoft in a technical role")

    assert decision.action == InvitationAction.ACCEPT
    assert decision.reason


def test_invitation_decision_rejects_invalid_action():
    with pytest.raises(ValidationError):
        InvitationDecision(action="maybe", reason="not a real action")


def test_invitation_model_defaults_decision_to_none():
    invitation = Invitation(name="Jane Doe", profile="https://www.linkedin.com/in/jane-doe", job_title="Software Engineer", mutual_connections=True)

    assert invitation.decision is None
    assert invitation.mutual_connections is True


def test_run_and_log_agent_logs_case_without_calling_azure_openai(monkeypatch, tmp_path):
    fake_decision = InvitationDecision(action=InvitationAction.IGNORE, reason="Recruiter")
    fake_usage = type("Usage", (), {"input_tokens": 10, "output_tokens": 5})()
    fake_result = type("Result", (), {"output": fake_decision, "usage": lambda self=None: fake_usage})()

    monkeypatch.setattr(invitations_manager.agent, "run", AsyncMock(return_value=fake_result))
    monkeypatch.chdir(tmp_path)

    decision = asyncio.run(run_and_log_agent("unit-test-case", "Some invitation text"))

    assert decision.action == InvitationAction.IGNORE
    logged = yaml.safe_load(Path("linkedin_invitation_cases.yaml").read_text())
    assert logged["cases"][0]["name"] == "unit-test-case"
    assert logged["cases"][0]["expected_output"]["action"] == "ignore"


def test_linkedin_invitation_cases_yaml_matches_expected_schema():
    """Regression coverage complementing evals.py: assert the eval dataset parses into
    cases with the shape run_and_log_agent produces, without running any live model
    grading (evals.py is the schema+grading run; this is schema-shape only)."""
    repo_root = Path(__file__).parent.parent.parent
    dataset = yaml.safe_load((repo_root / "linkedin_invitation_cases.yaml").read_text())

    assert "cases" in dataset
    assert len(dataset["cases"]) > 0
    for case in dataset["cases"]:
        assert "name" in case
        assert "inputs" in case
        expected_output = case.get("expected_output")
        if expected_output is not None:
            InvitationDecision(**expected_output)
