# LinkedIn Opportunity Message Analysis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an accuracy-first CLI that incrementally collects relevant LinkedIn recruiting messages, extracts evidence-backed skills and experience once per opportunity, persists the private dataset locally, and generates grouped Markdown reports.

**Architecture:** Add an `analysis` subpackage, `src/linkedin_agent/analysis/`, exposed as the `linkedin-agent analyze` subcommand, for models, SQLite persistence, Playwright collection, Pydantic AI analysis, and reporting. It is a subpackage (not one workflow module) because of its five modules and its own SQLite persistence boundary; record that reason in the PR. Keep this pipeline independent from `linkedin_agent/inbox.py`, but open LinkedIn only through the shared read-only session in `linkedin_agent.linkedin.session` (lock and write guard, from #46); use deterministic code for identity, deduplication, counting, and report assembly, while LLM agents handle opportunity segmentation, grounded extraction, verification, normalization proposals, and taxonomy grouping.

**Tech Stack:** Python 3.10+, Playwright, Pydantic, Pydantic AI structured output, Azure OpenAI/OpenAI, SQLite from the standard library, pytest, pytest-playwright, pydantic-evals, Ruff, uv

**Spec:** `docs/superpowers/specs/2026-10-17-linkedin-opportunity-message-analysis-design.md`

## Global Constraints

- Analyze LinkedIn's Focused inbox and its Archived folder, never the Other inbox. Ignore in Agent Inbox archives conversations (#46), so declined recruiter messages are in Archived.
- Open LinkedIn only with `linkedin_agent.linkedin.session.open_linkedin(headless, unattended, lock_timeout=LOCK_TIMEOUT_SECONDS)` and never pass `approval`. Route every click through `linkedin_agent.linkedin.guard.safe_click`. Never type, press keys, or import `linkedin_agent.linkedin.actions`. Collection must not send, archive, or mark anything read.
- Use a short lock timeout and exit nonzero when another LinkedIn task holds the lock. Release the session before model analysis starts.
- Initial collection history is exactly 30 days unless `--initial-days` overrides it.
- Relevant role families are Machine Learning Engineer, AI/LLM Engineer, Applied Scientist, Research Engineer, and MLOps/ML Platform Engineer.
- Exclude Data Scientist, data-engineering-only, and mixed roles where machine learning is not the primary function.
- Require an identifiable role and concrete skills or experience; company identity may be confidential.
- Assign an opportunity to the reporting period containing its first recruiting message.
- Count each canonical item and taxonomy group at most once per distinct opportunity.
- Every retained extraction requires an exact quote in a stored source message.
- Raw messages, SQLite data, and reports stay under `.linkedin-analysis/` and must be git-ignored.
- Build models only with `linkedin_agent.llm.build_model(backend, azure_variant="invitations")` (the known-working `/openai/v1` + `AzureDeveloperCliCredential` Azure setup). Don't add model builders.
- Do not alter `linkedin_agent/inbox.py`, its urgency ranking, or Agent Inbox behavior and its live actions.
- Preserve multi-selector and accessibility-label scraping fallback chains.
- Use `uv run` for all repository commands and Ruff for linting and formatting.

## Review Focus

- LinkedIn exposes no durable message ID: an overlapping collection must update or revision-link the logical message without duplicating opportunities.
- A conversation contains two roles: segmentation must create separate opportunities and preserve each role's evidence.
- A role is adjacent or mixed: Data Scientist and primarily data-engineering work must remain excluded while configured ML-adjacent families remain included.
- The model returns a plausible but nonexistent quote: validation must reject it and expose the failed item rather than count it.
- A conversation was ignored in Agent Inbox (archived) after an earlier run: it must be found in Archived and updated by URL, not duplicated or lost.
- Opening conversations during collection must not mark them read: every messaging write is blocked by the guard.
- A run partially fails after collecting data: successful raw data must persist, watermarks must not advance incorrectly, and any generated report must be labeled partial with a nonzero exit.

---

### Task 1: Private Storage and Domain Contracts

**Files:**
- Create: `src/linkedin_agent/analysis/__init__.py`
- Create: `src/linkedin_agent/analysis/models.py`
- Create: `src/linkedin_agent/analysis/storage.py`
- Modify: `.gitignore`
- Test: `tests/unit/test_message_analysis_storage.py`

**Interfaces:**
- Produces: `MessageRecord`, `CollectedConversation`, `OpportunitySegment`, `ExtractedItem`, `CanonicalItem`, `TaxonomyGroup`, `CollectionSummary`, `AnalysisSummary`, and `ReportRequest` Pydantic models.
- Produces: `AnalysisStore(path: Path)` with `initialize()`, run-state methods, idempotent conversation/message upserts, opportunity/extraction persistence, taxonomy persistence, watermark access, and report-query methods.
- Consumes: SQLite from the Python standard library only.

- [ ] **Step 1: Write failing schema and privacy tests**

Add tests asserting that `AnalysisStore.initialize()` creates a versioned schema for runs, conversations, messages, message revisions, opportunities, opportunity-message links, extractions, canonical items, opportunity items, taxonomy groups, taxonomy memberships, and analysis state; `.linkedin-analysis/` is present in `.gitignore`.

- [ ] **Step 2: Run the storage tests and verify they fail**

Run: `uv run pytest tests/unit/test_message_analysis_storage.py -v`

Expected: FAIL because `linkedin_agent.analysis.models`, `AnalysisStore`, and the schema do not exist.

- [ ] **Step 3: Implement the domain models and schema migration**

Define exact enum-backed values for role family, relevance, item type, run stage, and run status. Implement `AnalysisStore.initialize() -> None` with an explicit schema version and transactional migration path that never drops existing personal data.

- [ ] **Step 4: Write failing identity and idempotency tests**

Add tests proving:

- the same observed message upserts once;
- a changed observation at the same logical position creates a linked revision;
- repeated opportunity persistence uses the conversation plus first recruiting message identity;
- two first recruiting messages in one conversation produce two opportunity IDs;
- failed transactions do not advance collection or analysis watermarks.

- [ ] **Step 5: Implement stable identities, transactional upserts, and watermark methods**

Use the conversation URL, author, best timestamp, message position, and original content hash for source identity when LinkedIn provides no durable ID. Keep original content immutable and attach edits as revisions.

- [ ] **Step 6: Run the storage tests**

Run: `uv run pytest tests/unit/test_message_analysis_storage.py -v`

Expected: PASS.

- [ ] **Step 7: Commit the storage foundation**

```bash
git add .gitignore src/linkedin_agent/analysis tests/unit/test_message_analysis_storage.py
git commit -m "feat(analysis): add private message analysis storage

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 2: Focused and Archived Incremental Collector

**Files:**
- Create: `src/linkedin_agent/analysis/scraper.py`
- Create: `tests/playwright/test_message_analysis_scraping.py`
- Create: `tests/playwright/fixtures/focused_inbox.html`
- Create: `tests/playwright/fixtures/focused_conversation_history.html`
- Create: `tests/playwright/fixtures/archived_inbox.html`
- Check: `tests/unit/test_no_message_writes.py` already scans `src/linkedin_agent/**` recursively, so it covers the collector

**Interfaces:**
- Consumes: `AnalysisStore`, `CollectedConversation`, and `MessageRecord` from Task 1.
- Consumes: `linkedin_agent.linkedin.session.open_linkedin` (session, lock, write guard) and `linkedin_agent.linkedin.guard.safe_click`.
- Produces: `async ensure_folder(page: Page, folder: Literal["focused", "archived"]) -> None`.
- Produces: `async collect_messages(page: Page, store: AnalysisStore, cutoff: datetime, overlap: timedelta) -> CollectionSummary`, covering Focused then Archived and recording each conversation's folder.
- Produces: selector fallback constants for the Focused tab, the Archived folder, conversation cards, message events, authors, bodies, timestamps, and scroll containers.

- [ ] **Step 1: Write failing folder fixture tests**

Add tests proving the collector selects Focused rather than Other, then the Archived folder, uses at least one accessibility-label fallback for each, and raises a specific `InboxFolderUnavailableError` naming the missing folder instead of reading an unknown inbox. Run the fixtures in a context with `install_linkedin_write_guard(context)` and assert that opening conversations produces no messaging write, even though the fixture page fires read-receipt and "mark as seen" requests.

- [ ] **Step 2: Run the folder tests and verify they fail**

Run: `uv run pytest tests/playwright/test_message_analysis_scraping.py -v`

Expected: FAIL because the scraper and fixtures do not exist.

- [ ] **Step 3: Implement folder activation and selector fallbacks**

Implement `ensure_folder()` with bounded waits and explicit errors, clicking only through `safe_click`. Do not fall back to the default visible inbox if the requested folder cannot be confirmed.

- [ ] **Step 4: Write failing collection-window and overlap tests**

Cover a 30-day cutoff in both folders, a conversation that moved from Focused to Archived between runs (updated by URL, not duplicated), seven-day incremental overlap, scrolling until older conversations are reached, machine-readable timestamps, displayed timestamp retention, and bounded older context that cannot establish an in-period opportunity.

- [ ] **Step 5: Implement incremental conversation and history collection**

Implement `collect_messages()` so raw data commits transactionally, content hashes make overlap idempotent, and the successful collection watermark advances only after the collection transaction succeeds.

- [ ] **Step 6: Write and satisfy the no-durable-ID review-focus test**

Simulate the same message appearing in an overlapping run with edited content. Assert one logical message, two revisions, and no duplicate conversation or opportunity source identity.

- [ ] **Step 7: Run the scraper and storage tests**

Confirm `tests/unit/test_no_message_writes.py` (which scans `src/linkedin_agent/**` recursively) lists the new files and passes, so the collector can't click, type, or use write selectors outside the guard.

Run: `uv run pytest tests/playwright/test_message_analysis_scraping.py tests/unit/test_message_analysis_storage.py tests/unit/test_no_message_writes.py -v`

Expected: PASS.

- [ ] **Step 8: Commit the collector**

```bash
git add src/linkedin_agent/analysis/scraper.py tests/playwright
git commit -m "feat(analysis): collect focused and archived messages incrementally

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 3: Opportunity Segmentation and Relevance

**Files:**
- Create: `src/linkedin_agent/analysis/agents.py`
- Create: `evals/analysis_run.py`
- Create: `evals/message_analysis_cases.yaml`
- Create: `tests/unit/test_message_analysis_opportunities.py`

**Interfaces:**
- Consumes: stored conversation messages and Task 1 domain models.
- Consumes: `linkedin_agent.llm.build_model(backend, azure_variant="invitations")` and `llm.model_settings()`.
- Produces: `create_opportunity_agent(model) -> Agent`.
- Produces: `async segment_pending_conversations(store: AnalysisStore, agent: Agent) -> AnalysisSummary`.

- [ ] **Step 1: Write failing deterministic orchestration tests**

Use a fake agent result to assert that one conversation can persist two opportunities keyed by their first recruiting messages and that rerunning the same result remains idempotent.

- [ ] **Step 2: Run the opportunity tests and verify they fail**

Run: `uv run pytest tests/unit/test_message_analysis_opportunities.py -v`

Expected: FAIL because the agents and orchestration do not exist.

- [ ] **Step 3: Implement model construction and structured opportunity output**

Build the model with `llm.build_model(backend, azure_variant="invitations")`. Define an inline system prompt and Pydantic output that returns distinct opportunities with company, role, role family, message IDs, first recruiting message, relevance, and grounded reason.

- [ ] **Step 4: Add relevance-boundary tests**

Assert inclusion for ML Engineer, AI/LLM Engineer, Applied Scientist, Research Engineer, and MLOps/ML Platform Engineer; assert exclusion for Data Scientist, data-engineering-only, and mixed roles where ML is secondary; assert `insufficient_detail` when no identifiable role or concrete expectations exist.

- [ ] **Step 5: Implement validation and persistence**

Reject agent outputs that reference unknown messages or omit the first recruiting message. Persist excluded and insufficient opportunities with reasons, but do not queue them for extraction.

- [ ] **Step 6: Add the two-roles review-focus test**

Use a conversation fixture containing two separate recruiting approaches. Assert two opportunities with separate evidence and reporting dates.

- [ ] **Step 7: Add synthetic evaluation cases**

Create non-personal YAML cases for every configured role family, excluded role, insufficient-detail message, mixed role, and multi-opportunity conversation. Implement `evals/analysis_run.py` to evaluate structured validity, relevance, and segmentation.

- [ ] **Step 8: Run tests and evaluations**

Run: `uv run pytest tests/unit/test_message_analysis_opportunities.py -v`

Expected: PASS.

Run: `uv run python -m evals.analysis_run`

Expected: All committed synthetic cases pass against the configured evaluation model; if credentials are unavailable, record that the manual evaluation could not run rather than weakening tests.

- [ ] **Step 9: Commit opportunity discovery**

```bash
git add src/linkedin_agent/analysis/agents.py evals/analysis_run.py evals/message_analysis_cases.yaml tests/unit/test_message_analysis_opportunities.py
git commit -m "feat(analysis): identify relevant recruiting opportunities

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 4: Grounded Extraction, Verification, and Normalization

**Files:**
- Modify: `src/linkedin_agent/analysis/agents.py`
- Create: `src/linkedin_agent/analysis/pipeline.py`
- Create: `tests/unit/test_message_analysis_extraction.py`
- Modify: `evals/message_analysis_cases.yaml`
- Modify: `evals/analysis_run.py`

**Interfaces:**
- Consumes: relevant persisted opportunities from Task 3.
- Produces: `create_extraction_agent(model) -> Agent`, `create_verification_agent(model) -> Agent`, and `create_normalization_agent(model) -> Agent`.
- Produces: `validate_evidence(item: ExtractedItem, messages: dict[str, MessageRecord]) -> bool`.
- Produces: `async analyze_pending_opportunities(store: AnalysisStore, agents: AnalysisAgents) -> AnalysisSummary`.

- [ ] **Step 1: Write failing exact-evidence tests**

Assert that an exact quote in the referenced message passes, a quote from another message fails, a paraphrase fails, and Unicode/whitespace normalization does not permit materially different text.

- [ ] **Step 2: Run the extraction tests and verify they fail**

Run: `uv run pytest tests/unit/test_message_analysis_extraction.py -v`

Expected: FAIL because evidence validation and the analysis pipeline do not exist.

- [ ] **Step 3: Implement structured extraction and deterministic evidence validation**

Return item type, source wording, proposed canonical label, exact quote, source message ID, and context. Exclude unsupported items while persisting their failed validation status.

- [ ] **Step 4: Write failing verification tests**

Use fake extraction and verifier agents to prove that confirmed items persist, rejected items remain auditable but uncounted, corrected items require a valid exact quote, and unresolved verification makes the opportunity partially failed.

- [ ] **Step 5: Implement the verification pass**

Run verification only after local quote validation. Persist model provenance and stage status for every attempt.

- [ ] **Step 6: Write failing normalization and once-per-opportunity tests**

Assert that `PyTorch experience` and `experience with PyTorch` map to `PyTorch`, aliases remain retained, repeated mentions produce multiple evidence rows but one opportunity-item membership, and the same item in another opportunity increments the count once.

- [ ] **Step 7: Implement canonical normalization**

Present existing canonical labels to the normalizer before allowing a new label. Preserve aliases and source extractions; perform deduplication through a unique opportunity/canonical-item constraint.

- [ ] **Step 8: Add the nonexistent-quote review-focus case**

Extend unit and synthetic evaluation data with an attractive but absent skill. Assert it is rejected, visible as a quality failure, and absent from counts.

- [ ] **Step 9: Run extraction tests and evaluations**

Run: `uv run pytest tests/unit/test_message_analysis_extraction.py -v`

Expected: PASS.

Run: `uv run python -m evals.analysis_run`

Expected: Grounding and normalization evaluation cases pass when model credentials are available.

- [ ] **Step 10: Commit grounded analysis**

```bash
git add src/linkedin_agent/analysis/agents.py src/linkedin_agent/analysis/pipeline.py evals/analysis_run.py evals/message_analysis_cases.yaml tests/unit/test_message_analysis_extraction.py
git commit -m "feat(analysis): extract and verify opportunity requirements

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 5: Hybrid Taxonomy and Deterministic Aggregation

**Files:**
- Modify: `src/linkedin_agent/analysis/agents.py`
- Modify: `src/linkedin_agent/analysis/pipeline.py`
- Create: `tests/unit/test_message_analysis_taxonomy.py`

**Interfaces:**
- Consumes: canonical opportunity-item memberships from Task 4.
- Produces: `create_taxonomy_agent(model) -> Agent`.
- Produces: `async update_taxonomy(store: AnalysisStore, agent: Agent) -> AnalysisSummary`.
- Produces: `aggregate_period(store: AnalysisStore, request: ReportRequest) -> PeriodAggregation`.

- [ ] **Step 1: Write failing stable and new-group tests**

Assert that an existing suitable group is reused, a new group can be added without renaming unrelated groups, every canonical item has one primary group, and taxonomy revisions retain version history.

- [ ] **Step 2: Run taxonomy tests and verify they fail**

Run: `uv run pytest tests/unit/test_message_analysis_taxonomy.py -v`

Expected: FAIL because taxonomy update and aggregation do not exist.

- [ ] **Step 3: Implement taxonomy structured output and validation**

Provide the current taxonomy, item counts, item types, and representative evidence to the agent. Reject outputs that omit items, assign an item to multiple primary groups, or mutate prior taxonomy history.

- [ ] **Step 4: Write failing aggregation tests**

Assert period assignment by first recruiting message, one canonical count per opportunity, one group count per opportunity even when several member items occur, excluded opportunities omitted, and current-versus-pinned taxonomy selection.

- [ ] **Step 5: Implement deterministic SQL/Python aggregation**

Do not ask the LLM to count. Return canonical counts, distinct-opportunity group counts, coverage totals, failure totals, and evidence references.

- [ ] **Step 6: Run taxonomy tests**

Run: `uv run pytest tests/unit/test_message_analysis_taxonomy.py -v`

Expected: PASS.

- [ ] **Step 7: Commit taxonomy and aggregation**

```bash
git add src/linkedin_agent/analysis/agents.py src/linkedin_agent/analysis/pipeline.py tests/unit/test_message_analysis_taxonomy.py
git commit -m "feat(analysis): group and aggregate opportunity requirements

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 6: Evidence-Backed Markdown Reports

**Files:**
- Create: `src/linkedin_agent/analysis/report.py`
- Create: `tests/unit/test_message_analysis_report.py`

**Interfaces:**
- Consumes: `PeriodAggregation` from Task 5.
- Produces: `render_report(aggregation: PeriodAggregation) -> str`.
- Produces: `write_report(aggregation: PeriodAggregation, output_dir: Path, generated_at: datetime) -> Path`.

- [ ] **Step 1: Write failing report-content tests**

Assert stable headings for metadata, coverage, canonical counts, grouped counts, evidence, and excluded/incomplete opportunities. Assert each evidence row contains company or confidentiality marker, role, validated LinkedIn URL, and exact snippet.

- [ ] **Step 2: Run report tests and verify they fail**

Run: `uv run pytest tests/unit/test_message_analysis_report.py -v`

Expected: FAIL because report rendering does not exist.

- [ ] **Step 3: Implement Markdown rendering**

Use GFM tables where they improve scanning, preserve a stable heading hierarchy, avoid printing raw message bodies outside evidence snippets, and label fallback timestamps.

- [ ] **Step 4: Write failing filename and partial-report tests**

Assert repeated date ranges create timestamped files such as `2026-09-01-to-2026-09-30--2026-10-17T043500Z.md`; partial analysis produces a prominent partial-result warning and enumerates failures.

- [ ] **Step 5: Implement private report writing**

Write only beneath `.linkedin-analysis/reports/`. Reject output paths that escape the private analysis directory.

- [ ] **Step 6: Run report tests**

Run: `uv run pytest tests/unit/test_message_analysis_report.py -v`

Expected: PASS.

- [ ] **Step 7: Commit report generation**

```bash
git add src/linkedin_agent/analysis/report.py tests/unit/test_message_analysis_report.py
git commit -m "feat(analysis): generate evidence-backed reports

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

### Task 7: CLI Orchestration, Failure Semantics, and Documentation

**Files:**
- Create: `src/linkedin_agent/analysis/command.py` (`add_arguments` with `collect`, `report`, and `run` subcommands, plus `run_command`)
- Modify: `src/linkedin_agent/cli.py` (register the `analyze` subcommand)
- Create: `tests/unit/test_message_analyzer_cli.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: storage, scraper, agents, pipeline, taxonomy, aggregation, and reporting interfaces from Tasks 1-6.
- Produces: `add_arguments(parser: argparse.ArgumentParser) -> None`, registered by `cli.py` as `linkedin-agent analyze`.
- Produces: `run_command(args: argparse.Namespace) -> int`.
- Produces: subcommands `collect`, `report`, and `run`, with `run` as the default behavior.

- [ ] **Step 1: Write failing parser and command-routing tests**

Assert defaults of `run`, `--initial-days 30`, a seven-day overlap, Azure backend for accuracy, private storage paths, explicit `--start`/`--end` report dates, and no model initialization for `collect` or ordinary `report`.

- [ ] **Step 2: Run CLI tests and verify they fail**

Run: `uv run pytest tests/unit/test_message_analyzer_cli.py -v`

Expected: FAIL because the CLI does not exist.

- [ ] **Step 3: Implement independent login, model, and command orchestration**

Open LinkedIn with `linkedin_agent.linkedin.session.open_linkedin` (which reuses `playwright/.auth/state.json` and the manual-login flow, holds the LinkedIn lock, and installs the write guard) only for the collection stage, and close it before analysis. Map `LinkedInBusyError` and `LoginRequiredError` to clear messages and a nonzero exit. Initialize Azure/OpenAI models only for analysis stages, and keep the existing workflows (`invitations.py`, `inbox.py`, `daily.py`) untouched.

- [ ] **Step 4: Write failing partial-run and resume tests**

Simulate a collector success followed by one opportunity analysis failure. Assert raw data remains committed, the analysis watermark does not advance, a labeled partial report is written when trustworthy results exist, and the command returns nonzero. Assert a later rerun resumes failed work without duplicating counts.

- [ ] **Step 5: Implement explicit stage and exit semantics**

`collect` scrapes only; `report` reads structured data; `run` collects, analyzes, updates taxonomy, and reports. Return zero only for a complete successful command.

- [ ] **Step 6: Document operation and privacy**

Add README commands, local-path behavior, first-run 30-day scope across Focused and Archived, the read-only guarantee, the advice not to run the initial import while acting in Agent Inbox (actions wait for the LinkedIn lock), incremental semantics, model-provider disclosure, private-data warning, and instructions for expanding the history window only after validation.

- [ ] **Step 7: Run focused tests**

Run: `uv run pytest tests/unit/test_message_analysis_storage.py tests/unit/test_message_analysis_opportunities.py tests/unit/test_message_analysis_extraction.py tests/unit/test_message_analysis_taxonomy.py tests/unit/test_message_analysis_report.py tests/unit/test_message_analyzer_cli.py tests/playwright/test_message_analysis_scraping.py tests/unit/test_no_message_writes.py -v`

Expected: PASS.

- [ ] **Step 8: Run full validation**

Run: `uv run ruff check --fix .`

Expected: PASS with no remaining diagnostics.

Run: `uv run ruff format .`

Expected: Completes successfully.

Run: `uv run pytest`

Expected: PASS.

Run: `uv run python -m evals.analysis_run`

Expected: All committed synthetic cases pass when configured model credentials are available; otherwise report the credential blocker explicitly.

- [ ] **Step 9: Commit the complete CLI**

```bash
git add src/linkedin_agent/analysis/command.py src/linkedin_agent/cli.py tests/unit/test_message_analyzer_cli.py README.md
git commit -m "feat(analysis): add linkedin opportunity analysis cli

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

