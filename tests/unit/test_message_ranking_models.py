"""Non-Playwright pytest backfill for inbox_manager.py's LLM-decision logic seams:
MessageRanking/ConversationMessage/InboxMessage model validation, and
rank_messages_for_reply()'s urgency-sort behavior with a mocked ranking agent (no Azure
OpenAI calls - a fake object with an async `run` method is passed directly, since
rank_messages_for_reply takes the agent as a parameter rather than importing a
module-level global).

The async rank_messages_for_reply() calls are driven via asyncio.run() from plain (sync)
test functions rather than async def tests with pytest-asyncio/anyio, to avoid adding a
dependency not required for mocking. See tests/conftest.py for why these asyncio.run()
tests are ordered before pytest-playwright's sync `page`-fixture tests.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from inbox_manager import ConversationMessage, InboxMessage, MessageRanking, rank_messages_for_reply


def test_message_ranking_accepts_valid_urgency_score():
    ranking = MessageRanking(reason="Bug report for a GitHub product", urgency_score=9, suggested_reply="Thanks, looking into it now.")

    assert ranking.urgency_score == 9


def test_conversation_message_requires_all_fields():
    with pytest.raises(ValidationError):
        ConversationMessage(author="Sam Colleague", content="Hey")  # missing timestamp


def test_inbox_message_ranking_defaults_to_none():
    message = InboxMessage(sender_name="Sam Colleague", last_three_messages=[], conversation_url="https://www.linkedin.com/messaging/thread/1")

    assert message.ranking is None


def test_rank_messages_for_reply_sorts_by_urgency_without_calling_azure_openai():
    low_priority = InboxMessage(
        sender_name="Recruiter Bot",
        last_three_messages=[ConversationMessage(author="Recruiter Bot", content="Are you open to new roles?", timestamp="9:00 AM")],
        conversation_url="https://www.linkedin.com/messaging/thread/low",
    )
    high_priority = InboxMessage(
        sender_name="Sam Colleague",
        last_three_messages=[ConversationMessage(author="Sam Colleague", content="This is blocking the release", timestamp="9:05 AM")],
        conversation_url="https://www.linkedin.com/messaging/thread/high",
    )

    fake_agent = AsyncMock()
    fake_agent.run.side_effect = [
        type("Result", (), {"output": MessageRanking(reason="recruiter", urgency_score=1, suggested_reply="")})(),
        type("Result", (), {"output": MessageRanking(reason="blocking release", urgency_score=9, suggested_reply="On it.")})(),
    ]

    ranked = asyncio.run(rank_messages_for_reply([low_priority, high_priority], fake_agent))

    assert [m.sender_name for m in ranked] == ["Sam Colleague", "Recruiter Bot"]
    assert ranked[0].ranking.urgency_score == 9


def test_rank_messages_for_reply_defaults_ranking_when_agent_errors():
    message = InboxMessage(
        sender_name="Sam Colleague",
        last_three_messages=[ConversationMessage(author="Sam Colleague", content="Hi", timestamp="9:00 AM")],
        conversation_url="https://www.linkedin.com/messaging/thread/1",
    )
    failing_agent = AsyncMock()
    failing_agent.run.side_effect = RuntimeError("simulated Azure OpenAI failure")

    ranked = asyncio.run(rank_messages_for_reply([message], failing_agent))

    assert ranked[0].ranking.urgency_score == 1
    assert ranked[0].ranking.reason == "Error analyzing message"
