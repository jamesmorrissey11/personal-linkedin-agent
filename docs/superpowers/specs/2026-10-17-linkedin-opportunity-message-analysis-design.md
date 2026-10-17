---
title: LinkedIn Opportunity Message Analysis
date: 2026-10-17
status: draft
---

# LinkedIn Opportunity Message Analysis

## Intent

Add a separate command-line capability that turns relevant LinkedIn recruiting messages into a trustworthy, reusable dataset about the skills and experience expected of machine learning engineers and similar roles.

The first release establishes the analysis foundation: collect messages incrementally from the Focused inbox, identify distinct relevant job opportunities, extract and normalize the skills and experience mentioned in each opportunity, retain the raw and structured data locally, and generate an evidence-backed local report for a selected period.

The design prioritizes extraction quality and traceability over model cost and runtime. The initial import is limited to the previous 30 days so the collection and analysis approach can be validated before processing more history.

## Goals

- Analyze only conversations from LinkedIn's Focused inbox.
- Identify recruiting and job opportunities for machine learning engineering, AI or LLM engineering, applied scientist, research engineer, and MLOps or machine learning platform roles.
- Exclude unrelated roles, including data engineering opportunities, and messages that contain too little company or role detail to support useful analysis.
- Treat clearly distinct roles in the same LinkedIn conversation as separate opportunities.
- Count each normalized skill or experience at most once per distinct opportunity.
- Retain the original message text, source metadata, structured extraction, model provenance, and report history locally.
- Produce a Markdown report containing:
  - counts for each normalized skill or experience;
  - a hybrid taxonomy that preserves stable core groups while allowing new groups;
  - aggregate counts for each group;
  - the contributing opportunities and supporting message snippets.
- Process new or changed content incrementally after the initial 30-day import.
- Use structured LLM outputs and dedicated analysis passes where they improve accuracy.

## Non-Goals

- Comparing two periods, plotting multi-period trends, or generating narrative market forecasts.
- Sending messages, replying to recruiters, accepting invitations, or changing the existing human-review workflow.
- Replacing the urgency-ranking behavior in `inbox_manager.py`.
- Analyzing LinkedIn's Other inbox or non-LinkedIn sources.
- Treating data-engineering-only roles as relevant.
- Building a web interface, notebook, or Agent Inbox analysis view.
- Automatically deleting or expiring retained message data.
- Processing more than the initial 30-day history until the approach has been reviewed and refined.

## User Experience

The new entry point will be a separate script:

```shell
uv run python message_analyzer.py
```

On the first run, the command will:

1. Reuse the existing Playwright login state in `playwright/.auth/state.json`.
2. Open LinkedIn Messaging and select the Focused inbox.
3. Collect conversations and messages from the previous 30 days.
4. Identify distinct recruiting opportunities and classify their relevance.
5. Extract, verify, and normalize skills and experience from relevant opportunities.
6. Update the local taxonomy.
7. Write a Markdown report and print its path.

Later runs will collect messages newer than the last successful collection watermark, with a bounded overlap to catch delayed or edited content. Reporting can be rerun without scraping or repeating opportunity-level extraction.

Proposed command options:

```shell
uv run python message_analyzer.py collect
uv run python message_analyzer.py report
uv run python message_analyzer.py run
uv run python message_analyzer.py run --initial-days 30
uv run python message_analyzer.py report --start 2026-09-01 --end 2026-09-30
uv run python message_analyzer.py run --model-backend azure
```

`run` is the default and performs collection, analysis, and report generation. `collect` only scrapes and persists raw conversation data; it does not invoke analysis agents or update the taxonomy. `report` operates only on retained structured data and therefore does not require LinkedIn or model access unless taxonomy regeneration is explicitly requested.

## Architecture

### Separate End-to-End CLI

`message_analyzer.py` will own this workflow rather than adding an analysis mode to `inbox_manager.py`. The existing inbox manager currently captures only the last three messages from a fixed number of recent conversations and immediately ranks reply urgency. Longitudinal analysis requires complete opportunity context, incremental persistence, idempotent reprocessing, and report generation, which are a separate responsibility.

The new script will follow the established independent-entry-point convention. It will reproduce the required logging, CLI, Playwright session, and model setup rather than silently refactoring the existing managers into shared modules. Its Azure client setup will follow the known-working pattern in `invitations_manager.py`, not the intentionally divergent setup in `inbox_manager.py`.

### Processing Stages

```mermaid
flowchart LR
    A[Focused inbox collection] --> B[Local message store]
    B --> C[Opportunity segmentation and relevance]
    C --> D[Grounded skill and experience extraction]
    D --> E[Extraction verification]
    E --> F[Canonical normalization]
    F --> G[Hybrid taxonomy update]
    G --> H[Deterministic aggregation]
    H --> I[Markdown report with evidence]
```

Each stage persists its inputs, outputs, prompt version, model identifier, and status. A failed stage remains visible and retryable; it must not be converted into an empty or successful result.

New messages automatically mark their affected conversation and opportunities for reanalysis. A changed prompt version, model configuration, or normalization algorithm marks prior results stale but does not automatically incur model cost; the user must request reanalysis explicitly.

## Collection

### Focused Inbox

The collector will explicitly activate the Focused inbox before reading conversation cards. It will use resilient selector and accessibility-label fallback chains rather than a single CSS selector. If the Focused inbox cannot be identified, the run will fail clearly instead of analyzing an unknown inbox.

The collector will scroll the conversation list until it reaches the run's cutoff or LinkedIn exposes no additional conversations. Each opened conversation will retain:

- the canonical conversation URL;
- participant names;
- message author;
- raw message text;
- the best available machine-readable timestamp;
- the timestamp text shown by LinkedIn;
- collection time;
- stable content hashes.

The initial run stops at 30 days. Later runs begin from the last successful collection watermark with a configurable overlap, initially seven days. Existing message hashes make overlapping collection idempotent.

### Conversation History

For a newly discovered conversation, the collector will load enough history to cover the active 30-day window and any surrounding context needed to understand the role. For an existing conversation, it will collect new visible messages and combine them with retained local history before opportunity segmentation.

Messages older than the collection cutoff may be retained as bounded explanatory context, but they cannot establish an opportunity for the reporting period or contribute counted skills unless the opportunity's first recruiting message falls within that period.

LinkedIn timestamps can be incomplete or relative. The collector will prefer DOM timestamp attributes when available, retain the displayed timestamp unchanged, and record when a report date relies on collection time rather than a parsed message time.

## Local Persistence

Private analysis data will live under `.linkedin-analysis/`, which will be added to `.gitignore`.

```text
.linkedin-analysis/
├── analysis.sqlite3
└── reports/
    └── 2026-09-01-to-2026-09-30.md
```

SQLite is available in the Python standard library and is sufficient for the first release. The schema will preserve:

| Entity | Purpose |
|---|---|
| `runs` | Collection and analysis run status, cutoffs, prompt versions, and model provenance |
| `conversations` | Canonical LinkedIn thread identity and participants |
| `messages` | Raw message text, authorship, timestamps, hashes, and collection metadata |
| `opportunities` | Distinct role opportunities segmented from conversations |
| `opportunity_messages` | Evidence-bearing messages associated with each opportunity |
| `extractions` | Raw extracted skills and experiences with exact evidence references |
| `canonical_items` | Normalized skill or experience identities |
| `opportunity_items` | Deduplicated canonical items present in each opportunity |
| `taxonomy_groups` | Stable core groups and newly introduced groups |
| `taxonomy_memberships` | Canonical-item membership in taxonomy groups |
| `analysis_state` | Successful incremental watermarks and schema/prompt versions |

An opportunity's stable identity will be derived from its conversation, the first recruiting message assigned to that distinct role, and a persisted source-message identity. When LinkedIn exposes no durable message ID, the source identity will use the conversation, author, best timestamp, message position, and original content hash. Later observations that appear to be edits will be stored as message revisions linked to the original logical message rather than silently replacing it. Reprocessing the same messages therefore updates the existing opportunity instead of creating another count.

Schema migrations will be explicit and versioned. An incompatible schema must fail with an actionable message rather than being recreated and losing personal data.

## LLM Analysis

### Model Policy

Accuracy is the primary priority. The analyzer will default to the configured Azure OpenAI deployment and support an explicit OpenAI backend. Model names and deployments remain configuration, so the workflow can adopt newer capable models without source changes.

Every agent will use Pydantic AI structured output with bounded timeouts and explicit token limits. The stored provenance will include backend, model identifier, prompt version, and analysis timestamp.

### Opportunity Segmentation and Relevance

The first agent pass receives the retained messages for one conversation and returns zero or more distinct opportunities. Each opportunity includes:

- company and role title when available;
- the message identifiers that establish the opportunity;
- first and last relevant message times;
- role family;
- `relevant`, `irrelevant`, or `insufficient_detail`;
- a concise reason grounded in the messages.

Machine learning engineer, AI or LLM engineer, applied scientist, research engineer, and MLOps or machine learning platform roles are relevant. Data scientist, data-engineering-only, and mixed roles in which machine learning is not the primary function are irrelevant. A relevant opportunity must identify the role and contain concrete skills or experience expectations; the hiring company may remain confidential. Opportunities below this threshold are retained as `insufficient_detail` and excluded from counts.

Separating opportunities before extraction prevents a recruiter who discusses multiple roles in one thread from collapsing those roles into one count.

### Grounded Extraction

For each relevant opportunity, a dedicated extraction agent returns structured items with:

- item type, such as skill, technology, domain experience, responsibility, seniority, or qualification;
- the source wording;
- a proposed canonical label;
- an exact supporting quote;
- the source message identifier;
- optional context describing how the item is expected or used.

The initial report will combine these item types into one enumerable list while retaining their types for later filtering.

The application will verify that every quoted snippet occurs in the referenced raw message. Unsupported items will be marked invalid and excluded, not silently accepted.

### Verification

Because accuracy is prioritized over cost, a second agent pass will review each opportunity's proposed extraction against its source messages. It can confirm, reject, or correct items, but every retained item must still have an exact source quote.

Extraction failures and unresolved verification results will appear in a report-quality section so missing analysis is visible.

### Canonical Normalization

Normalization will map equivalent wording to a stable canonical item, such as mapping "PyTorch experience" and "experience with PyTorch" to `PyTorch`. The normalizer receives existing canonical labels before proposing a new one.

Deterministic code will enforce one count per canonical item per opportunity. Repeated mentions, follow-up messages, and multiple evidence snippets remain available for traceability but cannot inflate the count.

Canonical merges must preserve aliases and historical identities. A later normalization improvement updates memberships without deleting the source extraction.

### Hybrid Taxonomy

The taxonomy agent receives:

- the canonical items in the selected report period;
- their counts;
- the existing active taxonomy;
- representative evidence and item types.

It should reuse stable groups when they still fit, introduce a new group when the existing taxonomy would distort the data, and avoid renaming groups without a clear reason. Examples might include `Programming and Frameworks`, `Model Development`, `Production ML and MLOps`, `Cloud and Infrastructure`, and `Domain Experience`, but these are examples rather than a fixed initial taxonomy.

Group membership and taxonomy revisions are persisted. Reports show the taxonomy version so future trend work can distinguish data changes from taxonomy changes.

Each canonical item has one primary taxonomy group in the first release. A group's count is the number of distinct opportunities containing at least one item in that group, not the sum of its member-item counts. This prevents one opportunity containing several related skills from inflating the group total.

## Report

The generated Markdown report will use a stable heading hierarchy and contain:

1. Run metadata, date range, models, prompt versions, and taxonomy version.
2. Coverage and quality statistics:
   - Focused conversations inspected;
   - distinct opportunities found;
   - relevant, irrelevant, and insufficient-detail counts;
   - extraction or verification failures.
3. Canonical skill and experience counts, sorted by opportunity count.
4. Grouped counts using the active hybrid taxonomy.
5. Evidence details for each canonical item:
   - contributing company and role;
   - LinkedIn conversation link;
   - supporting message snippet.
6. Excluded and incomplete opportunities with reasons.

Counts will be computed in deterministic Python and SQL, not by asking an LLM to count. The LLM supplies classification, extraction, normalization proposals, and grouping; the application performs deduplication and arithmetic.

Reports contain private message snippets and will remain under the ignored `.linkedin-analysis/` directory.

An opportunity belongs to the reporting period containing its first recruiting message. Follow-ups in later periods update the retained opportunity but do not make the same opportunity a new observation in those periods.

Historical reports use the taxonomy version requested by the user and default to the current active taxonomy. Every report records that version, so a prior report remains interpretable even when a regenerated report uses a newer taxonomy.

Repeated reports for the same date range are timestamped rather than overwritten:

```text
.linkedin-analysis/reports/2026-09-01-to-2026-09-30--2026-10-17T043500Z.md
```

## Reliability and Error Handling

- A missing login, missing Focused tab, LinkedIn markup change, database migration problem, or required model configuration will terminate the affected stage with a clear error.
- Per-conversation scraping or analysis failures will be recorded with enough context to retry and will make the run partially failed rather than successful.
- The successful collection watermark advances only after collected data is committed.
- The successful analysis watermark advances only after all selected opportunities reach a terminal analysis state.
- Interrupted runs can resume without duplicating messages, opportunities, or counts.
- No broad exception handler will turn failures into empty classifications or zero-count reports.
- Model outputs are validated through Pydantic models and evidence checks before persistence.
- A partially failed `run` will generate a clearly labeled partial report when useful results exist and exit with a nonzero status. If no trustworthy results exist, it will skip report generation and exit nonzero.

## Testing and Evaluation

### Unit Tests

- SQLite schema creation, migration, upsert, and idempotent rerun behavior.
- Stable opportunity identity and separate opportunities within one conversation.
- One canonical item counted once per opportunity.
- Exact evidence quote validation.
- Canonical alias merging without source-data loss.
- Stable-group reuse and new-group addition.
- Report aggregation and private output location.
- Watermarks do not advance on partial failure.

### Playwright Fixture Tests

Extend the inbox fixtures to cover:

- selecting the Focused inbox;
- selector fallback behavior;
- scrolling conversation history;
- extracting full message content and machine-readable timestamps;
- stopping at the initial cutoff;
- collecting new messages during an overlapping incremental run.

### LLM Evaluations

Add a synthetic, non-personal evaluation dataset covering:

- relevant machine learning engineering roles;
- related roles that should be included;
- data engineering roles that should be excluded;
- insufficient-detail recruiter messages;
- multiple opportunities in one conversation;
- repeated mentions that should count once;
- aliases that should normalize together;
- unsupported extraction attempts.

The evaluation checks structured validity, relevance classification, opportunity separation, grounded evidence, and normalized-item expectations. Live personal messages must not be committed as fixtures or evaluation cases.

## Security and Privacy

- Raw messages and reports remain local and git-ignored.
- The command will clearly state that message content is sent to the configured model provider.
- Logs will avoid printing full message bodies by default.
- No LinkedIn authentication state, raw message data, database, or generated report will be committed.
- Conversation URLs are retained for traceability but validated as LinkedIn messaging URLs before rendering.

## Acceptance Criteria

- A first run collects up to 30 days of conversations from the Focused inbox and stores raw messages locally.
- A later run processes new or changed messages without duplicating previously stored data.
- Distinct roles in one conversation become distinct opportunities.
- Data-engineering-only and insufficient-detail opportunities are excluded from skill counts with visible reasons.
- Relevant opportunities produce evidence-backed structured skill and experience items.
- Every retained item points to an exact quote in a stored source message.
- Equivalent labels can normalize to one canonical item.
- Each canonical item contributes no more than one count per opportunity.
- The report shows canonical counts, hybrid grouped counts, opportunity sources, and evidence snippets.
- Existing `inbox_manager.py` urgency ranking and Agent Inbox behavior remain unchanged.
- Private raw data and generated reports are ignored by Git.

## Builder Decisions

The builder may choose:

- exact class and function names inside `message_analyzer.py`;
- the initial SQLite migration mechanism, provided it is explicit and preserves data;
- the exact Markdown table layouts;
- timeout and retry defaults consistent with the existing project;
- the precise selector fallback order after inspecting current LinkedIn markup and adding fixture coverage.

The builder may not replace the evidence requirement, deterministic counting, separate-opportunity behavior, Focused-inbox restriction, or private local storage with weaker alternatives.
