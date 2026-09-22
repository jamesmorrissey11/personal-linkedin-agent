> **Reference asset.** This is the implementation plan for [PR #15](https://github.com/jamesmorrissey11/personal-linkedin-agent/pull/15)
> ("Add Ollama local model backend (Gemma 3) as alternative to Azure OpenAI"), branch
> `feature/ollama-local-model-backend`. Kept here for future reference on what was decided, what was
> deviated from, what was validated, and what was flagged back to the user rather than resolved
> unilaterally. See [`docs/reports/local-model-serving-for-gemma3.md`](../reports/local-model-serving-for-gemma3.md)
> for the research that motivated choosing Ollama over llama.cpp/LM Studio/MLX/vLLM.

# Plan: Add Ollama (Gemma 3 12B) as local model backend for invitations_manager.py / inbox_manager.py

## Status: Implementation complete (branch `feature/ollama-local-model-backend`)

All 7 todos done. Summary of what shipped, deviations from the original plan, and validation evidence:

- **`invitations_manager.py`** (commit `f4bc7a1`): added `build_ollama_model()`/`build_azure_model()`/
  `build_model(backend)`/`build_agent(backend)`; module-level `agent = build_agent(MODEL_BACKEND)` (env
  var, default `"ollama"`); `--model-backend {ollama,azure,fallback}` CLI flag rebuilds the module-level
  `agent` in `__main__` if it differs from the env-var default. Azure client construction is now lazy
  (inside `build_azure_model()`), so importing the module with the default `ollama` backend requires zero
  Azure env vars — verified by importing with no `AZURE_*` vars set.
- **`inbox_manager.py`** (commit `7ce693f`): same pattern, reusing its existing (intentionally
  **not** fixed) divergent Azure client code inside `build_azure_model()`.
- **Docs** (commit `2d3b1f8`): filled in README's "Configuring Ollama Models" TODO section (install
  steps, `--model-backend`/`MODEL_BACKEND` table, eval-variance caveat), added a model-backend-selection
  subsection to `docs/ARCHITECTURE.md`, and committed `docs/reports/local-model-serving-for-gemma3.md`
  (the research report backing the Ollama recommendation) since both docs now link to it.
- Lint/format: `ruff check --fix .` and `ruff format .` both clean, no changes needed.

### Deviations from the original plan (found during implementation, resolved directly rather than left open)

1. **Module-level singleton rebuild mechanism** wasn't specified in the original plan. Resolved via a
   `build_agent(backend)` wrapper in `invitations_manager.py` (since `evals.py` imports `agent` directly)
   and a plain `model = build_model(...)` reassignment in `inbox_manager.py` (its `agent` is built lazily
   inside `create_message_ranking_agent`, called after CLI parsing) — both rely on Python's global-name
   lookup happening at call time, not import time, so no `global` keyword juggling was needed.
2. **Fallback-path test (todo/risk #1 — does `FallbackModel`'s default `fallback_on` catch a fully
   unreachable Ollama server, not just API-level errors?)** — **resolved, no code change needed.** Tested
   with `FallbackModel(unreachable_ollama, working_ollama)` (dead port → real Ollama instance, standing in
   for Azure since no Azure creds exist in this sandbox): the call succeeded via the second model,
   confirming connection-refused errors already trigger fallback with the library's default `fallback_on`.
3. **`gemma3:12b` could not be pulled in this sandbox** (8.1GB download hit `max retries exceeded: EOF`
   after ~4 minutes — a sandbox network/bandwidth limitation, not a code issue). Validated the entire
   mechanism instead against the already-installed `gemma3:latest` (4.3B) via `OLLAMA_MODEL=gemma3:latest`
   env override; the code path is identical regardless of which Gemma 3 size is pulled. **The user should
   run `ollama pull gemma3:12b` and re-run `python evals.py` on their own Apple Silicon Mac** to get
   size-accurate eval numbers before relying on it for unattended runs.

### Validation evidence (risk #2 from the original plan — Gemma 3 structured-output reliability)

Ran `python evals.py` twice against `gemma3:latest` (4.3B) via Ollama:
- Run 1: `CorrectDecisionEvaluator` average 0.800 (16/20 cases correct); `IsInstance` assertion passed on
  100% of cases (no malformed/unparseable structured output in either run).
- Run 2: `CorrectDecisionEvaluator` average 1.00 (20/20 cases correct); `IsInstance` 100%.

Conclusion: `NativeOutput`-based structured decisions parse reliably via Ollama+Gemma 3 (no schema
failures observed), but decision *correctness* varies run-to-run (80–100% on this 20-case dataset) — this
variance is now documented in the README as a caveat rather than silently accepted or silently blocking.
No pass-rate threshold was specified by the user for "good enough to default to `ollama`"; proceeded with
`ollama` as default per the explicit instruction ("always default to ollama"), with the variance
documented for the user to judge.

---

## Rubber-duck review (independent, gpt-5.4) and resolution

Dispatched a `rubber-duck` agent (different model than the implementer) against the full diff to check
for missing pieces, regressions, and reviewer-rejection risks. Findings and resolution:

**Fixed in follow-up commit:**
- Missing Azure env vars raised a raw `KeyError` for `azure`/`fallback` backends → now raises a
  `RuntimeError` naming the exact missing var(s) and suggesting `--model-backend ollama`.
- Removed model-identity logging (`Using Azure OpenAI with model %s`) was lost in the refactor → restored
  as `Using model backend=%s (model_name=%s)` in both scripts.
- Recorded eval cases (`linkedin_invitation_cases.yaml`) had `metadata: {}` with no record of which model
  produced the decision, which matters once `fallback` mode can silently switch mid-run → now records
  `metadata.model_name` from `agent_result.response.model_name` (confirmed this reflects the actual
  serving model, not just the configured backend, even under `FallbackModel`).
- `docs/ARCHITECTURE.md` overstated the fallback-triggers-on-connection-refused finding as a settled fact
  → reworded to "verified for `pydantic-ai==1.107.6`", not a documented library guarantee.
- README/ARCHITECTURE.md didn't mention that `fallback` mode still requires Azure credentials at startup
  (since `FallbackModel` builds both models eagerly, "tries Ollama first" doesn't mean "Azure is optional
  until needed") → clarified in both docs.
- README's "Running evaluations" section didn't mention that `evals.py` now defaults to evaluating Ollama
  (via the `agent` it imports) → added an explicit note plus `MODEL_BACKEND=azure python evals.py` to
  override.

**Flagged as fine, not changed** (per rubber duck's own assessment): the duplicated `build_*_model()`
functions across both scripts are consistent with the repo's existing "no shared module" convention, not
a design flaw to fix here; "no dependency bump needed" was independently re-confirmed correct.

**Not changed — requires user decision, not the agent's to make unilaterally:** the rubber duck's one
**blocking** finding is that defaulting to `ollama` for scripts that click real "Accept/Ignore" buttons on
live LinkedIn invitations is risky given eval correctness varied 80–100% (and was only measured against
`gemma3:latest` 4.3B, not the documented default `gemma3:12b`, due to a sandbox network limit on the 12B
pull). This directly conflicts with the user's earlier explicit instruction ("always default to ollama"),
so the implementation followed that instruction and documented the caveat rather than overriding the
user's decision. **Open follow-up:** if a safer default is wanted until 12B-specific numbers exist (e.g.
default `fallback` instead of pure `ollama`, or require an explicit `--model-backend ollama` opt-in rather
than a silent default), that would need a deliberate follow-up change — it did not ship as part of this PR.

---

## Original plan (as approved)

## Problem & approach

Both scripts currently hard-wire an Azure OpenAI client at import time. We need a `--model-backend`
selectable model source — `ollama` (default), `azure`, or `fallback` (Ollama first, Azure second) — built
via Pydantic AI's `OllamaModel`/`OllamaProvider` and `FallbackModel`, without ever requiring Azure
credentials to be present when the user isn't using Azure. `invitations_manager.py`'s existing Azure
client-setup pattern is the "known-working" one (per `.github/instructions/python.instructions.md`) and
must stay untouched when `azure`/`fallback` backends are selected; `inbox_manager.py`'s divergent Azure
setup is left as-is (not "fixed") per the same instructions — Ollama support is layered on top of each
script's existing pattern independently, with no shared module (matches existing repo convention).

Confirmed via sandbox check: installed `pydantic-ai==1.107.6` (not the `1.0.0b1` mentioned in
`docs/ARCHITECTURE.md`'s tech-debt list — that note is stale) already exposes `OllamaModel`,
`OllamaProvider`, and `FallbackModel`, so **no dependency version bump is required**.

## Key decisions (confirmed with user)

- **Default backend: `ollama`.** Neither script should construct/require an Azure client unless the
  user explicitly selects `azure` or `fallback`. This means Azure client construction must become lazy
  (moved inside a `build_model()`-style function gated on the selected backend), not top-level
  module-load code as it is today.
- **Fallback order: local first.** In `fallback` mode, `FallbackModel(ollama_model, azure_model)` — try
  Ollama, fall back to Azure OpenAI on failure.
- **Selection mechanism: both.** `MODEL_BACKEND` env var (`ollama` default) read from `.env`, with a
  `--model-backend {ollama,azure,fallback}` CLI flag on both scripts that overrides the env var when
  passed.
- **`inbox_manager.py` scope:** add the same `--model-backend`/`MODEL_BACKEND` selection there too, but
  reuse `inbox_manager.py`'s own existing (divergent, possibly-broken) Azure setup verbatim when `azure`/
  `fallback` is selected — do not silently "fix" it to match `invitations_manager.py`. Flag the divergence
  to the user again at review time rather than resolving it as part of this change.
- **Eval validation:** no code changes to `evals.py`. It imports `agent` directly from
  `invitations_manager`, and since the default backend is now `ollama`, running `python evals.py` as-is
  will automatically validate `linkedin_invitation_cases.yaml` against Gemma 3 via Ollama with zero Azure
  dependency. This is a manual validation step during implementation, not a new automated CI check.

## Open questions / risks to flag during implementation (not blocking the plan)

1. **`FallbackModel`'s default `fallback_on`** only catches `ModelAPIError`-family exceptions. If the
   Ollama server isn't running at all, the client raises a connection-level error (e.g. `httpx.ConnectError`)
   *before* it becomes a `ModelAPIError`. Need to verify during implementation whether Pydantic AI wraps
   this correctly for `fallback_on` to trigger — if not, `fallback_on` must be widened. This is called out
   as a concrete test case in the todos.
2. **Gemma 3 structured-output reliability** (`NativeOutput(InvitationDecision)` / `NativeOutput(MessageRanking)`)
   via Ollama is a documented soft spot for the Gemma family (see `docs/reports/local-model-serving-for-gemma3.md`
   footnotes 23-25). The plan includes running `evals.py` against Ollama and documenting pass rate /
   failure modes; if reliability is poor, a follow-up (e.g. `OpenAIModelProfile` override, prompt tweak, or
   reverting default to `azure`) will be flagged as a decision for the user rather than silently patched.
3. **`OLLAMA_MODEL` default** is `gemma3:12b` per the research report's recommendation; this requires the
   user to have run `ollama pull gemma3:12b` locally — plan includes a README step for this, not an
   automated pull.

## Todos

See SQL `todos` table for authoritative tracking; summary:

1. Add `MODEL_BACKEND`, `OLLAMA_BASE_URL`, `OLLAMA_MODEL` config plumbing (env vars + defaults) — no
   infra/Bicep changes needed since these aren't provisioned Azure outputs; document in README instead of
   `write_dot_env.sh`/`.ps1` (those stay Azure-only, per `infra.instructions.md`).
2. Refactor `invitations_manager.py`'s model construction into a `build_model(backend: str)` function
   supporting `ollama` (default) / `azure` / `fallback`, lazily constructing the Azure client only when
   needed; add `--model-backend` CLI flag.
3. Apply the same pattern to `inbox_manager.py`, reusing its existing (unfixed) Azure client code inside
   the lazy-construction branch; add matching `--model-backend` CLI flag.
4. Validate `evals.py` against the new Ollama default: run it, capture pass/fail rate vs. the existing
   Azure baseline, and document results/known failure modes in the PR description (and README if a
   long-term caveat emerges).
5. Test the `fallback` backend's failure path explicitly (Ollama not running → Azure fallback fires) to
   resolve open question #1 above; adjust `fallback_on` if needed.
6. Update `README.md`'s existing "Configuring Ollama Models" TODO section with real setup steps (install
   Ollama, `ollama pull gemma3:12b`, `MODEL_BACKEND`/`--model-backend` usage, note on Gemma 3 tool-calling
   caveats), and update `docs/ARCHITECTURE.md`'s entry-points/known-issues sections to describe the new
   backend-selection mechanism.
7. Lint/format (`ruff check --fix .`, `ruff format .`) and run `python evals.py` as final validation
   before opening the PR; follow `make-repo-contribution` skill for branch naming, commits, and PR
   description (no CI runs lint automatically, per `python.instructions.md`).
