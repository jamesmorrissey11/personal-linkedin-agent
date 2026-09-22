import asyncio
import logging
import os

import azure.identity
from dotenv import load_dotenv
from openai import AsyncOpenAI
from playwright.async_api import Page, async_playwright
from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from rich.logging import RichHandler

# Setup logging with rich
logging.basicConfig(level=logging.WARNING, format="%(message)s", datefmt="[%X]", handlers=[RichHandler(show_level=True)])
logger = logging.getLogger("inbox_manager")
logger.setLevel(logging.INFO)

load_dotenv()

# Model backend selection: "ollama" (default, local, no Azure credentials required), "azure", or
# "fallback" (try Ollama first, fall back to Azure OpenAI on failure). Override via MODEL_BACKEND env
# var or the --model-backend CLI flag.
MODEL_BACKEND = os.environ.get("MODEL_BACKEND", "ollama")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:12b")


def build_ollama_model() -> OllamaModel:
    """Build the local Ollama model. Requires `ollama serve` running locally with OLLAMA_MODEL pulled."""
    return OllamaModel(OLLAMA_MODEL, provider=OllamaProvider(base_url=OLLAMA_BASE_URL))


def build_azure_model() -> OpenAIModel:
    """Build the Azure OpenAI model using this script's existing client-setup pattern.

    Note: this diverges from `invitations_manager.py`'s Azure client setup (base URL suffix, sync vs.
    async credential, deprecated `OpenAIModel` vs. `OpenAIChatModel`) — see
    `.github/instructions/python.instructions.md`. Left as-is intentionally; not fixed as part of adding
    local-model support.
    """
    required_vars = ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_CHAT_DEPLOYMENT"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        raise RuntimeError(f"Missing required Azure OpenAI environment variable(s) for --model-backend azure/fallback: {', '.join(missing_vars)}. Set them in .env, or use --model-backend ollama (the default) to run without Azure credentials.")
    token_provider = azure.identity.get_bearer_token_provider(
        azure.identity.DefaultAzureCredential(),
        "https://cognitiveservices.azure.com/.default",
    )
    azure_client = AsyncOpenAI(
        base_url=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=token_provider,
    )
    return OpenAIModel(os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"], provider=OpenAIProvider(openai_client=azure_client))


def build_model(backend: str):
    """Build the Pydantic AI model for the given backend ("ollama", "azure", or "fallback").

    Azure credentials are only read/required when "azure" or "fallback" is selected, so the default
    "ollama" backend never assumes Azure OpenAI is configured or reachable. Note that "fallback"
    constructs the Azure model eagerly (FallbackModel requires both models up front), so Azure
    credentials must still be present at startup even though Ollama is tried first at request time.
    """
    if backend == "ollama":
        chosen_model = build_ollama_model()
    elif backend == "azure":
        chosen_model = build_azure_model()
    elif backend == "fallback":
        chosen_model = FallbackModel(build_ollama_model(), build_azure_model())
    else:
        raise ValueError(f"Unknown model backend: {backend!r}. Expected 'ollama', 'azure', or 'fallback'.")
    logger.info("Using model backend=%s (model_name=%s)", backend, chosen_model.model_name)
    return chosen_model


model = build_model(MODEL_BACKEND)


class MessageRanking(BaseModel):
    reason: str
    urgency_score: int  # 1-10 scale
    suggested_reply: str


class ConversationMessage(BaseModel):
    author: str
    content: str
    timestamp: str


class InboxMessage(BaseModel):
    sender_name: str
    last_three_messages: list[ConversationMessage]
    conversation_url: str
    ranking: MessageRanking | None = None


async def get_logged_in_user_name(page: Page) -> str:
    """Extract the logged-in user's name from LinkedIn."""
    try:
        # Try to get the user's name from the profile button/dropdown
        profile_button = await page.query_selector("button[aria-label*='View profile']")
        if profile_button:
            # Get the aria-label which often contains the user's name
            aria_label = await profile_button.get_attribute("aria-label")
            if aria_label and "View profile for" in aria_label:
                name = aria_label.replace("View profile for", "").strip()
                if name:
                    return name

        # Alternative: try to get name from the "Me" dropdown
        me_button = await page.query_selector("button[aria-label='Open profile menu']")
        if me_button:
            await me_button.click()
            await page.wait_for_timeout(1000)

            # Look for the name in the dropdown
            name_element = await page.query_selector(".profile-rail-card__actor-link")
            if name_element:
                name = await name_element.inner_text()
                if name:
                    return name.strip()

        # Fallback: try to get from top navigation
        nav_name = await page.query_selector(".global-nav__me-photo")
        if nav_name:
            alt_text = await nav_name.get_attribute("alt")
            if alt_text:
                return alt_text.strip()

        return "Unknown User"

    except Exception as e:
        logger.warning(f"Could not extract logged-in user name: {e}")
        return "Unknown User"


def create_message_ranking_agent(logged_in_user: str):
    """Create a message ranking agent with the logged-in user's context."""
    system_prompt = f"""You are triaging messages for the inbox of user {logged_in_user}.

Analyze LinkedIn messages and score them by urgency for requiring a reply from {logged_in_user}.

Consider factors like:
* The message is reporting a bug or feature request for Microsoft/GitHub/Azure products that {logged_in_user} is involved with.
* The message is requesting that {logged_in_user} speak at an event or participate in a project.

If the message is from a recruiter, give it a low urgency score.
If {logged_in_user} was the most recent author in the conversation, give it a low urgency score.

For each message, provide:
- reason: explanation for the urgency score
- urgency_score: 1-10 scale (1=low urgency, 10=high urgency)
- suggested_reply: A professional, concise suggested response that {logged_in_user} could send. Keep it brief and appropriate to the context.
"""

    return Agent(
        model,
        system_prompt=system_prompt,
        output_type=NativeOutput(MessageRanking),
    )


async def get_inbox_messages(page: Page, num_messages: int = 20) -> list[InboxMessage]:
    """Navigate to LinkedIn messaging and extract recent messages."""
    logger.info("Navigating to LinkedIn messaging...")

    # Go to messaging
    await page.goto("https://www.linkedin.com/messaging/")
    await page.wait_for_load_state("load")

    # Wait for messages to load
    await page.wait_for_selector("li.msg-conversation-listitem", timeout=10000)

    # Get conversation elements
    conversation_elements = await page.query_selector_all("li.msg-conversation-listitem")
    messages = []

    for i, conversation in enumerate(conversation_elements[:num_messages]):
        try:
            sender_element = await conversation.query_selector("h3.msg-conversation-card__participant-names")
            sender_name = await sender_element.inner_text() if sender_element else "Unknown"

            # Click on the conversation to open it and get more details
            logger.info(f"Opening conversation with {sender_name}...")
            await conversation.click()

            # Wait for the conversation to load
            await page.wait_for_load_state("load")
            await page.wait_for_timeout(2000)  # Give it a moment to fully load

            # Try to get the full conversation URL from the current page
            conversation_url = page.url

            # Extract the last three messages from the conversation
            last_three_messages = []
            try:
                # Look for all message events in the conversation
                message_elements = await page.query_selector_all("li.msg-s-message-list__event")

                # Get the last 3 messages (or however many are available)
                recent_messages = message_elements[-3:] if len(message_elements) >= 3 else message_elements

                for msg_element in recent_messages:
                    try:
                        # Get the author name from the messagea
                        author_element = await msg_element.query_selector(".msg-s-message-group__name")
                        if not author_element:
                            # Try alternative selector
                            author_element = await msg_element.query_selector("a .msg-s-message-group__profile-link")

                        author = await author_element.inner_text() if author_element else "Unknown"

                        # Get the message content
                        content_element = await msg_element.query_selector("p.msg-s-event-listitem__body")
                        content = await content_element.inner_text() if content_element else "No content"

                        # Get the timestamp
                        timestamp_element = await msg_element.query_selector("time.msg-s-message-group__timestamp")
                        if not timestamp_element:
                            # Try alternative timestamp selector
                            timestamp_element = await msg_element.query_selector("time.msg-s-message-list__time-heading")

                        timestamp = await timestamp_element.inner_text() if timestamp_element else "Unknown time"

                        # Create the message object
                        conversation_message = ConversationMessage(author=author.strip(), content=content.strip(), timestamp=timestamp.strip())
                        last_three_messages.append(conversation_message)

                    except Exception as e:
                        logger.warning(f"Error extracting individual message: {e}")
                        continue

                logger.info(f"Extracted {len(last_three_messages)} messages for {sender_name}")

            except Exception as e:
                logger.warning(f"Could not extract messages for {sender_name}: {e}")
                # Add a default message if extraction fails
                last_three_messages.append(ConversationMessage(author=sender_name, content="Could not extract message content", timestamp="Unknown"))

            message = InboxMessage(sender_name=sender_name, last_three_messages=last_three_messages, conversation_url=conversation_url)
            messages.append(message)

        except Exception as e:
            logger.warning(f"Error extracting message {i}: {e}")
            continue

    return messages


async def rank_messages_for_reply(messages: list[InboxMessage], message_ranking_agent) -> list[InboxMessage]:
    """Rank messages by priority for requiring a reply."""
    ranked_messages = []

    for message in messages:
        # Format the last three messages for the ranking prompt
        messages_text = ""
        for i, msg in enumerate(message.last_three_messages, 1):
            messages_text += f"\nMessage {i}:\n"
            messages_text += f"  Author: {msg.author}\n"
            messages_text += f"  Content: {msg.content}\n"
            messages_text += f"  Timestamp: {msg.timestamp}\n"

        # Create prompt for the ranking agent
        ranking_prompt = f"""
Sender: {message.sender_name}
Conversation URL: {message.conversation_url}

Last Messages in Conversation:{messages_text}

Analyze this LinkedIn message thread and determine if it requires a reply and how urgent it is.
Consider the flow of conversation and whether the last message seems to be waiting for a response.
"""

        try:
            agent_result = await message_ranking_agent.run(ranking_prompt)
            message.ranking = agent_result.output
            if message.ranking:
                logger.info(f"Ranked message from {message.sender_name}: urgency score {message.ranking.urgency_score}")

        except Exception as e:
            logger.warning(f"Error ranking message from {message.sender_name}: {e}")
            # Default ranking if AI analysis fails
            message.ranking = MessageRanking(reason="Error analyzing message", urgency_score=1, suggested_reply="")

        ranked_messages.append(message)

    # Sort by urgency score (highest first)
    ranked_messages.sort(key=lambda x: x.ranking.urgency_score if x.ranking else 0, reverse=True)

    return ranked_messages


async def manage_linkedin_inbox(num_messages: int = 20) -> list[InboxMessage]:
    """Main function to manage LinkedIn inbox and rank top messages requiring replies."""
    logger.info("Starting LinkedIn inbox management...")

    # Set up the storage state for Playwright
    os.makedirs("playwright/.auth", exist_ok=True)
    if not os.path.exists("playwright/.auth/state.json"):
        with open("playwright/.auth/state.json", "w") as f:
            f.write("{}")

    async with async_playwright() as p:
        # Launch browser
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(storage_state="playwright/.auth/state.json")
        page = await context.new_page()

        # Check if the user is logged in
        await page.goto("https://www.linkedin.com/feed")
        if not page.url.startswith("https://www.linkedin.com/feed"):
            logger.info("User is not logged in. Please log in manually...")
            await page.goto("https://www.linkedin.com/login")
            await page.wait_for_url("https://www.linkedin.com/feed/**", timeout=120000)
            logger.info("Login detected. Saving storage state...")
            await context.storage_state(path="playwright/.auth/state.json")

        # Get the logged-in user's name
        logged_in_user = await get_logged_in_user_name(page)
        logger.info(f"Managing inbox for user: {logged_in_user}")

        # Create the message ranking agent with user context
        message_ranking_agent = create_message_ranking_agent(logged_in_user)

        # Get recent messages
        messages = await get_inbox_messages(page, num_messages)
        logger.info(f"Found {len(messages)} recent messages")

        # Rank messages for reply priority
        ranked_messages = await rank_messages_for_reply(messages, message_ranking_agent)

        # Generate report
        logger.info("\n=== LinkedIn Inbox Management Report ===")
        logger.info(f"Analyzed {len(ranked_messages)} messages")

        # Show all messages with suggested reply or emoji reaction
        logger.info("\nAll messages with suggested reply or emoji reaction:")
        for i, msg in enumerate(ranked_messages, 1):
            if msg.ranking:
                logger.info(f"\n{i}. {msg.sender_name} - Urgency Score: {msg.ranking.urgency_score}")
                if msg.last_three_messages:
                    latest_msg = msg.last_three_messages[-1]
                    logger.info(f"   Latest Message: {latest_msg.content}")
                reply_or_emoji = msg.ranking.suggested_reply if msg.ranking.suggested_reply else "👍"
                logger.info(f"   Suggested Reply/Emoji: {reply_or_emoji}")
                logger.info(f"   Conversation: {msg.conversation_url}")

        # Open the message with the highest urgency
        highest_urgency_msg = ranked_messages[0] if ranked_messages else None
        if highest_urgency_msg and highest_urgency_msg.conversation_url:
            logger.info(f"\nOpening highest urgency message: {highest_urgency_msg.sender_name} - {highest_urgency_msg.conversation_url}")
            await page.goto(highest_urgency_msg.conversation_url)
            await page.wait_for_load_state("load")
            await page.wait_for_timeout(3000)

        # Show summary by urgency ranges
        high_urgency = [msg for msg in ranked_messages if msg.ranking and msg.ranking.urgency_score >= 7]
        medium_urgency = [msg for msg in ranked_messages if msg.ranking and 4 <= msg.ranking.urgency_score < 7]
        low_urgency = [msg for msg in ranked_messages if msg.ranking and msg.ranking.urgency_score < 4]

        logger.info("\nUrgency breakdown:")
        logger.info(f"  High urgency (7-10): {len(high_urgency)} messages")
        logger.info(f"  Medium urgency (4-6): {len(medium_urgency)} messages")
        logger.info(f"  Low urgency (1-3): {len(low_urgency)} messages")

        await browser.close()

    return ranked_messages


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage LinkedIn inbox messages.")
    parser.add_argument("--num-messages", type=int, default=20, help="Number of recent inbox messages to analyze (default: 20).")
    parser.add_argument(
        "--model-backend",
        choices=["ollama", "azure", "fallback"],
        default=None,
        help=f"Model backend to use (default: MODEL_BACKEND env var, currently {MODEL_BACKEND!r}).",
    )
    args = parser.parse_args()

    if args.model_backend and args.model_backend != MODEL_BACKEND:
        model = build_model(args.model_backend)

    asyncio.run(manage_linkedin_inbox(args.num_messages))
