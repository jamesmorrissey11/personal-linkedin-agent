import argparse
import asyncio
import logging
import os
from contextlib import asynccontextmanager
from enum import Enum
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlparse, urlunparse

import azure.identity.aio
import yaml
from dotenv import load_dotenv
from openai import AsyncOpenAI
from playwright.async_api import ElementHandle, Page, async_playwright
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput
from pydantic_ai.models.fallback import FallbackModel
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.ollama import OllamaProvider
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.settings import ModelSettings
from rich.logging import RichHandler

from review_graph import GRAPH_ID
from review_queue import classify_review, enqueue_review, fetch_pending_reviews, fetch_resolved_reviews, find_review, get_review_client, mark_applied, supersede_review
from unattended import KNOWN_STREAK_STOP, HealthCheckError, LoginRequiredError, ReviewCounts

# Setup logging with rich
logging.basicConfig(level=logging.WARNING, format="%(message)s", datefmt="[%X]", handlers=[RichHandler(show_level=True)])
logger = logging.getLogger("invitations_manager")
logger.setLevel(logging.INFO)

PROFILE_NAVIGATION_TIMEOUT_MS = 45000
PROFILE_CONTENT_TIMEOUT_MS = 15000
NEWSLETTER_IGNORE_SELECTOR = "button[aria-label^='Ignore invitation for ']"
MAX_SCANNED_INVITATIONS = int(os.environ.get("MAX_SCANNED_INVITATIONS", "500"))
NO_PENDING_INVITATIONS_TEXT = "no pending invitations"
INVITATION_CARD_SELECTORS = [
    "div[role='listitem']:has(button[aria-label^='Ignore an invitation to connect from ']):has(a[href*='/in/'])",
    "main div[componentkey^='auto-component-']:has(button[aria-label*='Accept'])",
]

load_dotenv()

# Model backend selection: "ollama" (default), "openai", "azure", or "fallback" (try Ollama first,
# fall back to Azure OpenAI on failure). Override via MODEL_BACKEND env var or the --model-backend
# CLI flag.
MODEL_BACKEND = os.environ.get("MODEL_BACKEND", "ollama")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:latest")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")

# Bound every LLM call so a small local model stuck generating (Ollama runs with --context-shift, so it
# never hits the context limit) can't stall the run. The OpenAI SDK retries timeouts twice, so the
# worst case per call is roughly 3x LLM_TIMEOUT_SECONDS.
LLM_MODEL_SETTINGS = ModelSettings(
    max_tokens=int(os.environ.get("LLM_MAX_TOKENS", "512")),
    timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
)


def build_ollama_model() -> OllamaModel:
    """Build the local Ollama model. Requires `ollama serve` running locally with OLLAMA_MODEL pulled."""
    return OllamaModel(OLLAMA_MODEL, provider=OllamaProvider(base_url=OLLAMA_BASE_URL))


def build_openai_model() -> OpenAIChatModel:
    """Build a standard OpenAI API model using OPENAI_API_KEY."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing required OPENAI_API_KEY for --model-backend openai. Set it in .env or choose another backend.")
    openai_client = AsyncOpenAI(api_key=api_key)
    return OpenAIChatModel(OPENAI_MODEL, provider=OpenAIProvider(openai_client=openai_client))


def build_azure_model() -> OpenAIChatModel:
    """Build the Azure OpenAI model using this script's known-working client-setup pattern."""
    required_vars = ["AZURE_TENANT_ID", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_CHAT_DEPLOYMENT"]
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    if missing_vars:
        raise RuntimeError(f"Missing required Azure OpenAI environment variable(s) for --model-backend azure/fallback: {', '.join(missing_vars)}. Set them in .env, or use --model-backend ollama (the default) to run without Azure credentials.")
    token_provider = azure.identity.aio.get_bearer_token_provider(
        azure.identity.aio.AzureDeveloperCliCredential(tenant_id=os.environ["AZURE_TENANT_ID"]),
        "https://cognitiveservices.azure.com/.default",
    )
    azure_client = AsyncOpenAI(
        base_url=os.environ["AZURE_OPENAI_ENDPOINT"] + "/openai/v1",
        api_key=token_provider,
    )
    return OpenAIChatModel(os.environ["AZURE_OPENAI_CHAT_DEPLOYMENT"], provider=OpenAIProvider(openai_client=azure_client))


def build_model(backend: str):
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
        chosen_model = build_azure_model()
    elif backend == "fallback":
        chosen_model = FallbackModel(build_ollama_model(), build_azure_model())
    else:
        raise ValueError(f"Unknown model backend: {backend!r}. Expected 'ollama', 'openai', 'azure', or 'fallback'.")
    logger.info("Using model backend=%s (model_name=%s)", backend, chosen_model.model_name)
    return chosen_model


class InvitationAction(Enum):
    ACCEPT = "accept"
    IGNORE = "ignore"
    UNDECIDED = "undecided"


class InvitationDecision(BaseModel):
    action: InvitationAction
    reason: str


class ApprovedInvitationAction(BaseModel):
    action: Literal[InvitationAction.ACCEPT, InvitationAction.IGNORE]
    reason: str
    thread_id: str


class Invitation(BaseModel):
    name: str
    profile: str
    job_title: str
    mutual_connections: bool
    decision: InvitationDecision | None = None


INVITATION_DECISION_SYSTEM_PROMPT = """Decide whether to accept or ignore LinkedIn invitations based on the profile information provided.
Always ignore wealth advisors, financial advisors, financial planners, investment advisors, and wealth management professionals. Apply this rule first. It overrides every acceptance criterion, including technical roles, mutual connections, and employment at Microsoft.
Always ignore profiles that appear to be coaches (for example: coach, coaching, life coach, executive coach, career coach, leadership coach, mindset coach, or sales coach). This exclusion also overrides every acceptance criterion.
Otherwise, accept if the person has a technical role, or is a student studying Computer Science, Data Science, or Machine Learning, or has mutual connections, or works at Microsoft.
Ignore recruiters.
If you have any uncertainty at all as to whether the person meets the acceptance criteria, respond with 'undecided'."""


def build_agent(backend: str) -> Agent[None, InvitationDecision]:
    return Agent(
        build_model(backend),
        system_prompt=INVITATION_DECISION_SYSTEM_PROMPT,
        output_type=NativeOutput(InvitationDecision),
        model_settings=LLM_MODEL_SETTINGS,
    )


# Built at import time using MODEL_BACKEND so `evals.py`'s `from invitations_manager import agent` works
# without requiring CLI args; `--model-backend` (if passed) rebuilds this in the __main__ block below.
agent = build_agent(MODEL_BACKEND)


async def run_and_log_agent(case_name: str, input_message: str):
    """
    Run the agent on the input_message, log input/output as a YAML evals case, and return the decision.
    """
    log_path = "linkedin_invitation_cases.yaml"
    agent_result = await agent.run(input_message)
    decision = agent_result.output
    logger.info("%d input tokens, %d output tokens used for decision", agent_result.usage().input_tokens, agent_result.usage().output_tokens)
    case = {
        "name": case_name,
        "inputs": input_message,
        "expected_output": {
            "action": decision.action.value if decision else None,
            "reason": decision.reason if decision else None,
        }
        if decision
        else None,
        "metadata": {"model_name": agent_result.response.model_name},
    }
    out_path = Path(log_path)
    if out_path.exists():
        with out_path.open("r", encoding="utf-8") as f:
            dataset_dict = yaml.safe_load(f) or {"cases": []}
    else:
        dataset_dict = {"cases": []}
    dataset_dict["cases"].append(case)
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(dataset_dict, f, sort_keys=False, allow_unicode=True)
    return decision


async def try_decision(case_name: str, input_message: str, record_eval_cases: bool) -> tuple[InvitationDecision | None, str | None]:
    """Run the decision agent, returning (None, error) instead of raising if the LLM call fails or times out."""
    try:
        if record_eval_cases:
            return await run_and_log_agent(case_name, input_message), None
        agent_result = await agent.run(input_message)
        logger.debug(
            "%d input tokens, %d output tokens used for decision",
            agent_result.usage().input_tokens,
            agent_result.usage().output_tokens,
        )
        return agent_result.output, None
    except Exception as e:
        logger.warning(f"Error getting decision for {case_name}: {e!r}")
        return None, repr(e)


async def get_decision(case_name: str, input_message: str, record_eval_cases: bool) -> InvitationDecision | None:
    return (await try_decision(case_name, input_message, record_eval_cases))[0]


async def get_invitation_info(card) -> Invitation | None:
    def first_non_empty_line(text: str) -> str:
        for line in text.splitlines():
            stripped = line.strip()
            if stripped:
                return stripped
        return text.strip()

    # Fetch the primary profile link (most cards link to /in/ profiles)
    profile_link_element = await card.query_selector("a[href*='/in/']")
    if not profile_link_element:
        profile_link_element = await card.query_selector("a")
    if not profile_link_element:
        return None

    profile_link = await profile_link_element.get_attribute("href")
    if not profile_link:
        return None
    if not profile_link.startswith("http"):
        profile_link = f"https://www.linkedin.com{profile_link}"
    # Normalize URL: decode any percent-encoded characters to get clean URL
    parsed = urlparse(profile_link)
    decoded_path = unquote(parsed.path)
    profile_link = urlunparse(parsed._replace(path=decoded_path))

    # Resolve the invitee name from a list of possible selectors (new follower layout lacks <strong>)
    name_selectors = [
        "a > strong",
        "a span[aria-hidden='true']",
        "span[aria-hidden='true']",
        "span[dir='auto']",
    ]
    name = ""
    for selector in name_selectors:
        element = await card.query_selector(selector)
        if element:
            text = (await element.inner_text()).strip()
            if text:
                name = first_non_empty_line(text)
                break
    if not name:
        link_text = (await profile_link_element.inner_text()).strip()
        if link_text:
            name = first_non_empty_line(link_text)
    if not name:
        return None

    card_lines = [line.strip() for line in (await card.inner_text()).splitlines() if line.strip()]
    try:
        name_index = card_lines.index(name)
    except ValueError:
        name_index = -1

    job_title = "Unknown"
    for line in card_lines[name_index + 1 :]:
        if line in {"Accept", "Ignore"} or line.startswith("Reply to ") or "mutual connection" in line.lower():
            continue
        if line:
            job_title = line
            break

    if job_title == "Unknown":
        for selector in ["p:nth-of-type(2)", "span.t-14", "div.artdeco-entity-lockup__subtitle span"]:
            element = await card.query_selector(selector)
            if not element:
                continue
            text = (await element.inner_text()).strip()
            if text:
                job_title = first_non_empty_line(text)
                break

    # Check for mutual connections (single phrase)
    connection_info_element = await card.query_selector("*:has-text('mutual connection')")
    connection_info = (await connection_info_element.inner_text()).strip() if connection_info_element else ""
    has_mutual_connections = "mutual connection" in connection_info.lower()

    return Invitation(name=name, profile=profile_link, job_title=job_title, mutual_connections=has_mutual_connections)


async def get_profile_info(page: Page, profile_url: str) -> str:
    """Visit the profile page and extract relevant information."""
    new_page = await page.context.new_page()
    try:
        try:
            await new_page.goto(profile_url, wait_until="domcontentloaded", timeout=PROFILE_NAVIGATION_TIMEOUT_MS)
        except PlaywrightTimeoutError as timeout_error:
            logger.warning(
                "Timed out navigating to profile page %s; trying to extract any content that loaded. Error: %s",
                profile_url,
                timeout_error,
            )

        try:
            main_content = await new_page.wait_for_selector("main, div[role='main']", timeout=PROFILE_CONTENT_TIMEOUT_MS)
        except PlaywrightTimeoutError:
            main_content = None
        if main_content is None:
            logger.warning("Main content not found on profile page: %s (current URL: %s)", profile_url, new_page.url)
            return "Profile information not available because LinkedIn did not finish loading the profile page."

        profile_text = (await main_content.inner_text()).strip()
        if not profile_text:
            logger.warning("Profile page content was empty: %s", profile_url)
            return "Profile information not available because the profile page content was empty."
        return profile_text
    except PlaywrightError as playwright_error:
        logger.warning("Could not fetch profile information for %s: %s", profile_url, playwright_error)
        return "Profile information not available because LinkedIn could not load the profile page."
    finally:
        await new_page.close()


def approved_invitation_decision(resolved_review: dict) -> ApprovedInvitationAction | None:
    """Return a validated human decision, or fail closed for malformed review data."""
    values = resolved_review.get("values") or {}
    thread_id = resolved_review.get("thread_id")
    if not isinstance(thread_id, str) or not thread_id:
        logger.warning("Skipping invitation review without a thread ID: %r", resolved_review)
        return None
    try:
        action = InvitationAction(values["decision"])
    except (KeyError, ValueError, TypeError):
        logger.warning("Skipping malformed invitation review: %r", values)
        return None
    if action not in {InvitationAction.ACCEPT, InvitationAction.IGNORE}:
        logger.warning("Skipping non-actionable invitation review: %r", values)
        return None
    return ApprovedInvitationAction(action=action, reason="Approved by human via Agent Inbox", thread_id=thread_id)


async def execute_approved_action(card: ElementHandle, decision: ApprovedInvitationAction) -> bool:
    """Execute a validated human-approved invitation action."""
    if decision.action == InvitationAction.ACCEPT:
        accept_button = await card.query_selector("button[aria-label*='Accept']")
        if accept_button:
            await accept_button.click()
            return True
        else:
            logger.warning("Accept button not found on the card.")
    elif decision.action == InvitationAction.IGNORE:
        ignore_button = await card.query_selector("button[aria-label*='Ignore']")
        if ignore_button:
            await ignore_button.click()
            return True
        else:
            logger.warning("Ignore button not found on the card.")
    return False


NEEDS_JUDGMENT_LABEL = "Needs your judgment"


async def queue_invitation_proposal(review_client, invitation: Invitation, decision: InvitationDecision | None, error: str | None = None) -> bool:
    """Queue every invitation for human review (failing open); never mutate LinkedIn.

    Undecided or failed decisions are queued with a "Needs your judgment" label so they are never hidden.
    """
    input_data = {"name": invitation.name, "profile": invitation.profile, "job_title": invitation.job_title}
    if decision is not None and decision.action in {InvitationAction.ACCEPT, InvitationAction.IGNORE}:
        input_data["reason"] = f"Agent proposes **{decision.action.value}**.\n\n{decision.reason}"
    else:
        input_data["label"] = NEEDS_JUDGMENT_LABEL
        input_data["reason"] = f"The agent was undecided.\n\n{decision.reason}" if decision is not None else f"The agent could not decide (LLM error: {error or 'unknown'})."
    return await enqueue_review(review_client, GRAPH_ID, invitation.profile, input_data)


@asynccontextmanager
async def linkedin_session(headless: bool, unattended: bool):
    """Yield (context, page) for a logged-in LinkedIn session.

    When unattended (or headless) an expired session raises LoginRequiredError instead of waiting for a human.
    """
    os.makedirs("playwright/.auth", exist_ok=True)
    if not os.path.exists("playwright/.auth/state.json"):
        with open("playwright/.auth/state.json", "w") as f:
            f.write("{}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        try:
            context = await browser.new_context(storage_state="playwright/.auth/state.json")
            page = await context.new_page()
            await page.goto("https://www.linkedin.com/feed")
            if not page.url.startswith("https://www.linkedin.com/feed"):
                if headless or unattended:
                    raise LoginRequiredError("LinkedIn session expired; log in again with a visible browser.")
                logger.info("User is not logged in. Please log in manually...")
                await page.goto("https://www.linkedin.com/login")
                await page.wait_for_url("https://www.linkedin.com/feed/**", timeout=120000)
                logger.info("Login detected. Saving storage state...")
                await context.storage_state(path="playwright/.auth/state.json")
            yield context, page
        finally:
            await browser.close()


async def get_invitation_cards(page: Page) -> list[ElementHandle]:
    for selector in INVITATION_CARD_SELECTORS:
        cards = await page.query_selector_all(selector)
        if cards:
            return cards
    html_snippet = (await page.content())[:2000]
    logger.warning("No invitation cards found. HTML snippet (2k chars): %s", html_snippet)
    return []


async def page_reports_no_invitations(page: Page) -> bool:
    return NO_PENDING_INVITATIONS_TEXT in (await page.content()).lower()


async def collect_invitation_profiles(page: Page) -> tuple[set[str], bool]:
    """Scroll the whole invitation list. Returns (profiles, complete); complete is False if any card could not be parsed or a cap was hit."""
    profiles: set[str] = set()
    complete = True
    consecutive_no_new_scrolls = 0
    while consecutive_no_new_scrolls < 5:
        found_new = False
        for card in await get_invitation_cards(page):
            invitation = await get_invitation_info(card)
            if not invitation:
                complete = False
                continue
            if invitation.profile not in profiles:
                profiles.add(invitation.profile)
                found_new = True
        if len(profiles) >= MAX_SCANNED_INVITATIONS:
            return profiles, False
        consecutive_no_new_scrolls = 0 if found_new else consecutive_no_new_scrolls + 1
        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.9)")
        await asyncio.sleep(2)
    return profiles, complete


async def close_stale_invitations(review_client, page: Page) -> int:
    """Supersede pending invitation reviews whose profile is gone from LinkedIn.

    Only closes when the full, non-empty list was scanned with every card parsed; otherwise keeps everything.
    """
    pending = await fetch_pending_reviews(review_client, GRAPH_ID)
    if not pending:
        return 0
    profiles, complete = await collect_invitation_profiles(page)
    if not profiles:
        if await page_reports_no_invitations(page):
            logger.info("LinkedIn reports no pending invitations; keeping %d pending review(s) for the next non-empty scan.", len(pending))
            return 0
        raise HealthCheckError("Invitation scan returned zero cards; not closing any stale reviews.")
    if not complete:
        logger.warning("Invitation list scan was incomplete; not closing any stale reviews.")
        return 0
    closed = 0
    for key, thread_id in pending.items():
        if key not in profiles:
            await supersede_review(review_client, thread_id, "Invitation no longer pending on LinkedIn (handled outside Agent Inbox).")
            logger.info("Closed stale invitation review %s as superseded.", key)
            closed += 1
    return closed


async def apply_resolved_invitations(page: Page, review_client, human_decisions: dict[str, dict], num_to_process: int) -> list[Invitation]:
    """Click the Accept/Ignore a human chose in Agent Inbox for visible invitations."""
    results: list[Invitation] = []
    processed_profiles: set[str] = set()
    consecutive_no_new_scrolls = 0
    max_no_new_scrolls = 5  # fail-safe to avoid infinite loop

    while len(results) < num_to_process:
        # DOM changes remove accepted/ignored cards, so always re-read the visible set
        invitation_cards = await get_invitation_cards(page)
        if not invitation_cards:
            logger.info("No invitation cards currently visible.")
            break
        new_card_seen = False
        for card in invitation_cards:
            if len(results) >= num_to_process:
                break
            invitation = await get_invitation_info(card)
            if not invitation or invitation.profile in processed_profiles:
                continue
            processed_profiles.add(invitation.profile)
            new_card_seen = True
            resolved_review = human_decisions.get(invitation.profile)
            if not resolved_review:
                continue
            human_decision = approved_invitation_decision(resolved_review)
            if human_decision and await execute_approved_action(card, human_decision):
                invitation.decision = InvitationDecision(action=human_decision.action, reason=human_decision.reason)
                await mark_applied(review_client, human_decision.thread_id)
                logger.info(f"Applied human-approved decision for {invitation.name}: {human_decision.action.value}")
                results.append(invitation)
                await asyncio.sleep(1)
        if len(results) >= num_to_process:
            break
        if new_card_seen:
            consecutive_no_new_scrolls = 0
            continue
        consecutive_no_new_scrolls += 1
        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.9)")
        await asyncio.sleep(2)
        if consecutive_no_new_scrolls >= max_no_new_scrolls:
            break
    return results


async def propose_new_invitations(page: Page, review_client, num_to_process: int, record_eval_cases: bool, unattended: bool) -> tuple[list[Invitation], ReviewCounts]:
    """Scan until caught up with already-known invitations, queueing every new one (failing open)."""
    results: list[Invitation] = []
    counts = ReviewCounts()
    seen_profiles: set[str] = set()
    known_streak = 0
    consecutive_no_new_scrolls = 0
    max_no_new_scrolls = 5  # fail-safe to avoid infinite loop

    while True:
        invitation_cards = await get_invitation_cards(page)
        if not invitation_cards:
            if await page_reports_no_invitations(page):
                logger.info("LinkedIn reports no pending invitations.")
            elif unattended and not seen_profiles:
                raise HealthCheckError("Invitation scan returned zero cards; treating as a scrape failure, not 'nothing new'.")
            break

        new_card_seen = False
        stop = False
        for card in invitation_cards:
            invitation = await get_invitation_info(card)
            if not invitation or invitation.profile in seen_profiles:
                continue
            seen_profiles.add(invitation.profile)
            new_card_seen = True

            existing = await find_review(review_client, GRAPH_ID, invitation.profile)
            if existing:
                # Known item: no LLM call, and it must not count toward the processing cap.
                bucket = classify_review(existing)
                setattr(counts, bucket, getattr(counts, bucket) + 1)
                known_streak += 1
                if known_streak >= KNOWN_STREAK_STOP:
                    logger.info("Reached %d consecutive already-known invitations; caught up.", known_streak)
                    stop = True
                    break
                continue
            known_streak = 0

            if counts.new >= num_to_process:
                counts.cap_hit = True
                logger.warning("Reached the safety cap of %d new invitations; more may be waiting.", num_to_process)
                stop = True
                break

            decision_message = f"Name: {invitation.name}, Job Title: {invitation.job_title}, Profile Link: {invitation.profile}, Connection Info: {invitation.mutual_connections}."
            decision, error = await try_decision(invitation.name, decision_message, record_eval_cases)
            if decision is not None and decision.action == InvitationAction.UNDECIDED:
                logger.info(f"Agent is undecided about {invitation.name}. Fetching profile information...")
                profile_info = await get_profile_info(page, invitation.profile)
                detailed_message = f"Full profile information for {invitation.name} ({invitation.job_title}):\n{profile_info}\n\nBased on this additional information, should we accept or ignore this invitation? Provide a reason for your decision."
                detailed_decision, error = await try_decision(invitation.name, detailed_message, record_eval_cases)
                if detailed_decision is not None:
                    decision = detailed_decision
                logger.info(f"Agent's final decision for {invitation.name}: {decision.action} - {getattr(decision, 'reason', '')}")

            if await queue_invitation_proposal(review_client, invitation, decision, error):
                counts.new += 1
                if decision is None or decision.action == InvitationAction.UNDECIDED:
                    counts.needs_judgment += 1
                logger.info("Queued %s for %s; LinkedIn was not modified.", decision.action.value if decision else "failed decision", invitation.name)
            else:
                counts.already_queued += 1

            invitation.decision = decision
            results.append(invitation)
            await asyncio.sleep(1)

        if stop:
            break
        if new_card_seen:
            consecutive_no_new_scrolls = 0
        else:
            consecutive_no_new_scrolls += 1
        logger.info(f"Scrolling for more invitations ({counts.total} seen so far)...")
        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.9)")
        await asyncio.sleep(2)
        if consecutive_no_new_scrolls >= max_no_new_scrolls:
            logger.info("Reached the end of the invitation list.")
            break
    return results, counts


async def process_linkedin_invitations(num_to_process: int = 100, record_eval_cases: bool = False, headless: bool = False, apply_inbox_decisions: bool = False, cleanup_stale: bool = False, unattended: bool = False) -> ReviewCounts:
    """Propose new invitations (default), or apply human decisions and/or close stale items.

    `num_to_process` is a safety cap on NEW items; already-known invitations never count toward it.
    """
    logger.info("Starting LinkedIn invitation processing...")
    review_client = get_review_client()
    human_decisions: dict[str, dict] = {}
    if apply_inbox_decisions:
        human_decisions = await fetch_resolved_reviews(review_client, GRAPH_ID)
        logger.info("Found %d resolved Agent Inbox review(s).", len(human_decisions))

    counts = ReviewCounts()
    async with linkedin_session(headless, unattended) as (_context, page):
        logger.info("Navigating to invitation manager...")
        await page.goto("https://www.linkedin.com/mynetwork/invitation-manager/")
        await page.wait_for_load_state("load")
        newsletter_invitation_count = len(await page.query_selector_all(NEWSLETTER_IGNORE_SELECTOR))
        if newsletter_invitation_count:
            logger.info("Found %d newsletter invitation(s); left pending because no human-approved action exists.", newsletter_invitation_count)
        await page.wait_for_selector("main#workspace, main, div[role='main']")

        if apply_inbox_decisions or cleanup_stale:
            if apply_inbox_decisions:
                applied = await apply_resolved_invitations(page, review_client, human_decisions, num_to_process)
                counts.applied = len(applied)
                logger.info("Applied %d human-approved invitation decision(s).", len(applied))
            if cleanup_stale:
                if apply_inbox_decisions:
                    await page.goto("https://www.linkedin.com/mynetwork/invitation-manager/")
                    await page.wait_for_load_state("load")
                counts.superseded = await close_stale_invitations(review_client, page)
            return counts

        results, counts = await propose_new_invitations(page, review_client, num_to_process, record_eval_cases, unattended)

        logger.info("\n=== LinkedIn Invitation Processing Report ===")
        logger.info("Invitations: %s", counts.describe())
        logger.info("Newsletter invitations left pending: %d", newsletter_invitation_count)
        for invitation in results:
            decision = invitation.decision
            outcome = decision.action.value if decision else "needs judgment (LLM failed)"
            logger.info(f"- [{outcome}] {invitation.name} ({invitation.job_title})\n  Profile: {invitation.profile}\n  Reason: {decision.reason if decision else 'n/a'}")
    return counts


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process LinkedIn invitations.")
    parser.add_argument("--num-to-process", type=int, default=100, help="Safety cap on NEW invitations to queue per run (default: 100). Scanning stops earlier once it reaches invitations already known.")
    parser.add_argument("--record-eval-cases", action="store_true", help="Record eval cases to YAML file.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode.")
    parser.add_argument("--send-to-inbox", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--apply-inbox-decisions", action="store_true", help="Apply accept/ignore decisions a human made in Agent Inbox.")
    parser.add_argument("--cleanup-stale", action="store_true", help="Close pending reviews for invitations no longer on LinkedIn (only after a full, non-empty scan).")
    parser.add_argument(
        "--model-backend",
        choices=["ollama", "openai", "azure", "fallback"],
        default=None,
        help=f"Model backend to use (default: MODEL_BACKEND env var, currently {MODEL_BACKEND!r}).",
    )
    args = parser.parse_args()

    if args.model_backend and args.model_backend != MODEL_BACKEND:
        agent = build_agent(args.model_backend)

    asyncio.run(process_linkedin_invitations(args.num_to_process, record_eval_cases=args.record_eval_cases, headless=args.headless, apply_inbox_decisions=args.apply_inbox_decisions, cleanup_stale=args.cleanup_stale))
