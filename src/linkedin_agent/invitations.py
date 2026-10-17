"""Invitation workflow: propose accept/ignore for each pending LinkedIn invitation and queue it for review.

Never clicks Accept or Ignore. A human decides each item in Agent Inbox, and the review graph acts on it.
"""

import argparse
import asyncio
import logging
from pathlib import Path

import yaml
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from pydantic_ai import Agent, NativeOutput

from linkedin_agent.linkedin.models import Invitation, InvitationAction, InvitationDecision
from linkedin_agent.linkedin.pages import collect_invitation_profiles, get_invitation_cards, get_invitation_info, page_reports_no_invitations
from linkedin_agent.linkedin.session import open_linkedin
from linkedin_agent.llm import build_model, check_backend, default_model_backend, model_settings
from linkedin_agent.review.graphs import GRAPH_ID
from linkedin_agent.review.queue import check_review_server, classify_review, enqueue_review, fetch_pending_reviews, find_pending_review, get_review_client, supersede_review
from linkedin_agent.runtime import KNOWN_STREAK_STOP, HealthCheckError, ReviewCounts, next_step

logger = logging.getLogger("invitations_manager")
logger.setLevel(logging.INFO)

PROFILE_NAVIGATION_TIMEOUT_MS = 45000
PROFILE_CONTENT_TIMEOUT_MS = 15000
NEWSLETTER_IGNORE_SELECTOR = "button[aria-label^='Ignore invitation for ']"
EVAL_CASES_PATH = Path(__file__).resolve().parents[2] / "evals" / "invitation_cases.yaml"


INVITATION_DECISION_SYSTEM_PROMPT = """Decide whether to accept or ignore LinkedIn invitations based on the profile information provided.
Always ignore wealth advisors, financial advisors, financial planners, investment advisors, and wealth management professionals. Apply this rule first. It overrides every acceptance criterion, including technical roles, mutual connections, and employment at Microsoft.
Always ignore profiles that appear to be coaches (for example: coach, coaching, life coach, executive coach, career coach, leadership coach, mindset coach, or sales coach). This exclusion also overrides every acceptance criterion.
Otherwise, accept if the person has a technical role, or is a student studying Computer Science, Data Science, or Machine Learning, or has mutual connections, or works at Microsoft.
Ignore recruiters.
If you have any uncertainty at all as to whether the person meets the acceptance criteria, respond with 'undecided'."""


def build_agent(backend: str) -> Agent[None, InvitationDecision]:
    return Agent(
        build_model(backend, azure_variant="invitations"),
        system_prompt=INVITATION_DECISION_SYSTEM_PROMPT,
        output_type=NativeOutput(InvitationDecision),
        model_settings=model_settings(),
    )


_agent: Agent[None, InvitationDecision] | None = None


def configure(backend: str | None = None) -> Agent[None, InvitationDecision]:
    """Build the decision agent for `backend` (default: MODEL_BACKEND). CLI commands call this at startup so a misconfigured backend fails fast."""
    global _agent
    _agent = build_agent(backend or default_model_backend())
    return _agent


def get_agent() -> Agent[None, InvitationDecision]:
    return _agent or configure()


async def run_and_log_agent(case_name: str, input_message: str):
    """
    Run the agent on the input_message, log input/output as a YAML evals case, and return the decision.
    """
    agent_result = await get_agent().run(input_message)
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
    out_path = EVAL_CASES_PATH
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
        agent_result = await get_agent().run(input_message)
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


def linkedin_session(headless: bool, unattended: bool):
    """Yield (context, page) for a logged-in LinkedIn session; see `linkedin.session.open_linkedin`."""
    return open_linkedin(headless, unattended)


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
        if key not in profiles and await supersede_review(review_client, thread_id, "Invitation no longer pending on LinkedIn (handled outside Agent Inbox)."):
            logger.info("Closed stale invitation review %s as superseded.", key)
            closed += 1
    return closed


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

            existing = await find_pending_review(review_client, GRAPH_ID, invitation.profile)
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


async def process_linkedin_invitations(num_to_process: int = 100, record_eval_cases: bool = False, headless: bool = False, cleanup_stale: bool = False, unattended: bool = False) -> ReviewCounts:
    """Propose new invitations (default), or close stale items.

    `num_to_process` is a safety cap on NEW items; already-known invitations never count toward it.
    """
    logger.info("Starting LinkedIn invitation processing...")
    review_client = get_review_client()

    counts = ReviewCounts()
    async with linkedin_session(headless, unattended) as (_context, page):
        logger.info("Navigating to invitation manager...")
        await page.goto("https://www.linkedin.com/mynetwork/invitation-manager/")
        await page.wait_for_load_state("load")
        newsletter_invitation_count = len(await page.query_selector_all(NEWSLETTER_IGNORE_SELECTOR))
        if newsletter_invitation_count:
            logger.info("Found %d newsletter invitation(s); left pending because no human-approved action exists.", newsletter_invitation_count)
        await page.wait_for_selector("main#workspace, main, div[role='main']")

        if cleanup_stale:
            counts.superseded = await close_stale_invitations(review_client, page)
            logger.info("Closed %d invitation review(s) already handled on LinkedIn.", counts.superseded)
            return counts

        results, counts = await propose_new_invitations(page, review_client, num_to_process, record_eval_cases, unattended)

        logger.info("\n=== LinkedIn Invitation Processing Report ===")
        logger.info("Invitations: %s", counts.describe())
        logger.info("Newsletter invitations left pending: %d", newsletter_invitation_count)
        for invitation in results:
            decision = invitation.decision
            outcome = decision.action.value if decision else "needs judgment (LLM failed)"
            logger.info(f"- [{outcome}] {invitation.name} ({invitation.job_title})\n  Profile: {invitation.profile}\n  Reason: {decision.reason if decision else 'n/a'}")
        if not unattended:
            logger.info(next_step(counts, "invitation", "invitations"))
    return counts


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--num-to-process", type=int, default=100, help="Safety cap on NEW invitations to queue per run (default: 100). Scanning stops earlier once it reaches invitations already known.")
    parser.add_argument("--record-eval-cases", action="store_true", help="Record eval cases to evals/invitation_cases.yaml.")
    parser.add_argument("--headless", action="store_true", help="Run browser in headless mode.")
    parser.add_argument("--send-to-inbox", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--cleanup-stale", action="store_true", help="Close pending reviews for invitations no longer on LinkedIn (only after a full, non-empty scan).")


def run_command(args: argparse.Namespace) -> int:
    check_review_server()
    backend = args.model_backend or default_model_backend()
    configure(backend)
    check_backend(backend)
    asyncio.run(process_linkedin_invitations(args.num_to_process, record_eval_cases=args.record_eval_cases, headless=args.headless, cleanup_stale=args.cleanup_stale))
    return 0
