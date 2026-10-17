"""#42 review UX: Agent Inbox descriptions, end-of-run next steps, and one-line setup errors."""

import argparse

import pytest

from linkedin_agent import cli, daily, llm, runtime
from linkedin_agent.linkedin.session import LinkedInBusyError
from linkedin_agent.review import queue
from linkedin_agent.review.graphs import build_interrupt, build_message_interrupt
from linkedin_agent.runtime import LoginRequiredError, ReviewCounts, SetupError, next_step

INVITATION = {"name": "Ada Lovelace", "job_title": "ML Engineer at Analytical Engines", "profile": "https://www.linkedin.com/in/ada/", "label": "Agent proposes accept", "reason": "Technical role with mutual connections."}
MESSAGE = {
    "sender_name": "Grace Hopper",
    "conversation_url": "https://www.linkedin.com/messaging/thread/2-x/",
    "urgency_score": 7,
    "label": "Low urgency (3/10)",
    "latest_message": "Hi James,\n\nCan we talk Friday about the compiler role?",
    "reason": "Direct question about a meeting.",
    "suggested_reply": "Friday works. 10am?",
}


def test_invitation_description_has_who_proposal_reason_link_and_outcomes():
    description = build_interrupt(INVITATION)["description"]

    assert description.startswith("**Ada Lovelace** · ML Engineer at Analytical Engines")
    assert "**Agent's proposal:** Agent proposes accept" in description
    assert "Technical role with mutual connections." in description
    assert "[View profile on LinkedIn](https://www.linkedin.com/in/ada/)" in description
    assert "**Accept** accepts this invitation on LinkedIn right away. **Ignore** ignores it on LinkedIn right away." in description


def test_message_description_quotes_the_whole_latest_message_and_states_outcomes():
    description = build_message_interrupt(MESSAGE)["description"]

    assert description.startswith("**Grace Hopper** · urgency 7/10 · Low urgency (3/10)")
    assert "> Hi James,\n>\n> Can we talk Friday about the compiler role?" in description
    assert "**Why it may need a reply:** Direct question about a meeting." in description
    assert "[Open the conversation on LinkedIn](https://www.linkedin.com/messaging/thread/2-x/)" in description
    assert "**Accept** sends the suggested reply exactly as shown. **Edit** sends your edited text instead. **Ignore** archives the conversation on LinkedIn." in description


def test_message_without_a_suggestion_explains_edit_instead_of_accept():
    payload = build_message_interrupt({**MESSAGE, "suggested_reply": " ", "urgency_score": None, "label": "Couldn't score"})

    assert payload["config"]["allow_accept"] is False
    assert payload["description"].startswith("**Grace Hopper** · not scored · Couldn't score")
    assert "there's no suggested reply. **Edit** sends the text you write, exactly once." in payload["description"]


def test_very_long_messages_are_truncated_with_a_pointer_to_linkedin():
    description = build_message_interrupt({**MESSAGE, "latest_message": "x" * 5000})["description"]

    assert "*(truncated; open the conversation for the rest)*" in description
    assert len(description) < 4000


def test_failure_banner_stays_first():
    assert build_interrupt({**INVITATION, "last_error": "LinkedIn login expired."})["description"].startswith("⚠️ **Last attempt failed:** LinkedIn login expired.\n\n**Ada Lovelace**")


@pytest.mark.parametrize(
    ("counts", "expected"),
    [
        (ReviewCounts(new=3), "Next: review 3 new invitation item(s) in Agent Inbox (http://localhost:3000)."),
        (ReviewCounts(cap_hit=True), "run `uv run linkedin-agent invitations` again with a higher cap"),
        (ReviewCounts(already_queued=4), "Nothing new to review. Next: `uv run linkedin-agent invitations` again later"),
    ],
)
def test_next_step_names_the_exact_next_action(counts, expected):
    assert expected in next_step(counts, "invitation", "invitations")


def test_unreachable_langgraph_server_is_a_setup_error_with_the_fix(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_URL", "http://127.0.0.1:9")

    with pytest.raises(SetupError) as raised:
        queue.check_review_server()

    assert raised.value.cause == "Can't reach the LangGraph server at http://127.0.0.1:9."
    assert "uv run linkedin-agent server" in raised.value.fix


def test_unreachable_ollama_is_a_setup_error_but_fallback_and_hosted_backends_are_not_probed(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:9/v1")

    with pytest.raises(SetupError, match="Ollama isn't reachable at http://127.0.0.1:9/v1"):
        llm.check_backend("ollama")
    for backend in ("fallback", "openai", "azure"):
        llm.check_backend(backend)


def test_missing_hosted_backend_settings_are_setup_errors(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(SetupError) as raised:
        llm.build_openai_model()

    assert isinstance(raised.value, RuntimeError) and "OPENAI_API_KEY" in raised.value.cause


def test_check_url_accepts_any_http_answer(monkeypatch):
    import urllib.error

    def http_error(url, timeout):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    monkeypatch.setattr("urllib.request.urlopen", http_error)

    runtime.check_url("http://localhost:2024/ok", "cause", "fix")


def run_cli_with(monkeypatch, error):
    def failing(args):
        raise error

    parser = argparse.ArgumentParser()
    parser.set_defaults(run_command=failing)
    monkeypatch.setattr(cli, "build_parser", lambda: parser)
    monkeypatch.setattr(cli, "configure_console_logging", lambda: None)
    return cli.main([])


@pytest.mark.parametrize(
    ("error", "code", "message"),
    [
        (SetupError("Can't reach the LangGraph server at http://localhost:2024.", "Start it with `uv run linkedin-agent server`."), 1, "error: Can't reach the LangGraph server at http://localhost:2024. Start it with `uv run linkedin-agent server`."),
        (LoginRequiredError("expired"), 2, "error: The LinkedIn login expired. Run the same command without --headless"),
        (LinkedInBusyError("busy"), 3, "error: Another LinkedIn task"),
    ],
)
def test_cli_prints_one_line_cause_and_fix_instead_of_a_traceback(monkeypatch, capsys, error, code, message):
    assert run_cli_with(monkeypatch, error) == code

    err = capsys.readouterr().err
    assert err.startswith(message) and err.count("\n") == 1 and "Traceback" not in err


def test_cli_turns_a_lost_langgraph_connection_into_one_line(monkeypatch, capsys):
    import httpx

    assert run_cli_with(monkeypatch, httpx.ConnectError("refused")) == 1
    assert "Lost the connection to the LangGraph server" in capsys.readouterr().err


def test_daily_setup_problem_notifies_and_exits_without_touching_linkedin(monkeypatch):
    notes = []
    monkeypatch.setattr(daily, "check_review_server", lambda: (_ for _ in ()).throw(SetupError("Can't reach the LangGraph server.", "Start it.")))
    monkeypatch.setattr(daily, "notify", lambda title, message: notes.append((title, message)))
    monkeypatch.setattr(daily, "run", lambda headless: pytest.fail("must not open LinkedIn"))
    monkeypatch.setattr(daily, "configure_file_logging", lambda: None)

    assert daily.run_command(argparse.Namespace(model_backend=None, headless=True)) == daily.EXIT_HEALTH
    assert notes == [("LinkedIn agent: setup problem", "Can't reach the LangGraph server. Start it.")]
