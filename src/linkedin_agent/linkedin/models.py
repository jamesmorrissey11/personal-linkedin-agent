"""Domain models shared by the LinkedIn scrapers, the LLM workflows, and the review queue."""

from enum import Enum

from pydantic import BaseModel


class InvitationAction(Enum):
    ACCEPT = "accept"
    IGNORE = "ignore"
    UNDECIDED = "undecided"


class InvitationDecision(BaseModel):
    action: InvitationAction
    reason: str


class Invitation(BaseModel):
    name: str
    profile: str
    job_title: str
    mutual_connections: bool
    decision: InvitationDecision | None = None


class ConversationMessage(BaseModel):
    author: str
    content: str
    timestamp: str


class MessageRanking(BaseModel):
    reason: str
    urgency_score: int  # 1-10 scale
    suggested_reply: str


class InboxMessage(BaseModel):
    sender_name: str
    last_three_messages: list[ConversationMessage]
    conversation_url: str
    ranking: MessageRanking | None = None
    known: str | None = None  # run-report bucket when an existing review already covers this message
    from_user: bool = False  # True only when the latest message's author exactly matches the logged-in user
