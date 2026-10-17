# Local Model-Serving Options for Gemma 3 on Apple Silicon (Alternative to Azure OpenAI)

**Research date:** 2026-09-22
**Scope:** Evaluate open-source model-serving frameworks capable of running Gemma 3 (9B/12B-class — Gemma 3 ships as 1B/4B/12B/27B, so "12B" is the closest match to "9B/12B-class") at usable interactive latency on an Apple Silicon MacBook Pro, as a drop-in alternative/fallback to Azure OpenAI for this project's Pydantic AI agents (`invitations_manager.py`, `inbox_manager.py`).

---

## Executive Summary

Four realistic options were evaluated: **Ollama**, **llama.cpp** (+ **LM Studio** as a GUI wrapper), **MLX/mlx-lm**, and **vLLM**. All except vLLM are strong candidates; vLLM's core is CUDA/ROCm/TPU-first and only offers an unaccelerated, experimental CPU backend on macOS (a newer `vllm-metal` plugin adds real Metal/MLX acceleration but is young and not Gemma-3-GGUF-compatible). **Ollama is the recommended default** — MIT-licensed, extremely active, ships native Metal acceleration on Apple Silicon, has a built-in OpenAI-compatible `/v1/chat/completions` endpoint, and Pydantic AI has first-class `OllamaProvider` support with documented code examples. **MLX/mlx-lm is the recommended power-user alternative** if squeezing maximum tokens/sec and lowest memory footprint out of the exact same Apple Silicon chip matters, since MLX is Apple's own unified-memory-native framework (no Metal port needed — it's designed for this hardware from scratch). Hard, controlled benchmark numbers for Gemma 3 12B specifically on M-series MacBook Pro hardware are surprisingly scarce across all sources checked (GitHub issues, HF discussions, benchmark repos, blogs); the few real data points found (~15–23.5 tok/s class) should be treated as directional, not authoritative, until validated on the target machine. A documented, real risk for all local-model paths is that Gemma 3's tool-calling/structured-output support through OpenAI-compatible APIs is less reliable than larger frontier models — this directly affects Pydantic AI's function-calling-based agent design and should be tested against this project's actual prompts before relying on it in production.

---

## Confidence Assessment

**High confidence (directly verified from primary sources — repo files, official docs):**
- Licenses for all four tools (MIT for Ollama/llama.cpp/MLX/mlx-lm, Apache 2.0 for vLLM, proprietary freeware for LM Studio app itself).
- All four/five tools expose OpenAI-compatible APIs.
- Native Metal/Apple Silicon GPU acceleration in Ollama, llama.cpp, and MLX (not CPU fallback).
- vLLM's mainline macOS support is genuinely CPU-only/experimental; Metal support is a separate young plugin (`vllm-metal`).
- Pydantic AI's exact code patterns for `OpenAIChatModel` + custom `base_url`, the dedicated `OllamaProvider`, `AzureProvider`, and `FallbackModel`.
- Gemma 3 family sizes are 1B/4B/12B/27B — **there is no 9B variant**; 12B is the nearest match to "9B/12B-class."

**Medium confidence (anecdotal but plausible, single-source):**
- ~23.5 tok/s for `gemma3:12b` on Mac Mini M4 Pro via Ollama (single GitHub issue reporter, no controlled methodology).
- ~15 tok/s for `gemma3:12b`/`4b` on M3 Pro 36GB via Ollama — but this was measured **during a KV-cache-quantization bug** that was later fixed, so it may understate current real-world performance.
- Proxy benchmarks (Llama 3 8B/70B on M1 Max/M2 Ultra/M3 Max) as a rough stand-in for Gemma 3 12B/27B-class performance, since no Gemma-3-specific, size-matched, controlled benchmark table exists in any source checked.

**Low confidence / explicit gaps (flagged, not fabricated):**
- No credible, controlled tokens/sec **or** time-to-first-token numbers exist for Gemma 3 12B specifically on M1/M2/M3/M4 **Pro/Max MacBook Pro** chips in any source accessible during this research (Reddit r/LocalLLaMA and general web search were blocked/rate-limited in the research environment — a genuine access gap, not evidence of "no such data exists" in the wild).
- One MLX benchmark data point citing "M5 Max" was found but is unverifiable against any real Apple chip lineup as of this writing and is explicitly excluded from the recommendation basis.
- Exact default quantization level Ollama uses for `gemma3:12b` (the untagged default pull) was not labeled on the model library page.

**Assumption made:** Because Gemma 3 has no 9B size, "9B/12B-class" in the original request is interpreted as the 12B variant throughout this report.

---

## Comparison Table

| | **Ollama** | **llama.cpp** | **LM Studio** | **MLX / mlx-lm** | **vLLM (mainline)** | **vllm-metal (plugin)** |
|---|---|---|---|---|---|---|
| License | MIT [^1] | MIT [^6] | Proprietary freeware (wraps OSS engines) [^9] | MIT (Apple) [^13] | Apache 2.0 [^19] | Apache 2.0 (same org) [^21] |
| Maintenance | 181K★, weekly releases, ~14–47 commits/wk [^2][^3] | 129K★, near-daily commits/releases [^7] | Weekly–biweekly release notes [^10] | 28.5K★ (mlx) / 7.1K★ (mlx-lm), releases every 2–6 wks [^14] | 92K★, releases ~every 2 wks [^20] | 1.76K★, tracks vLLM core releases [^22] |
| Apple Silicon accel. | Native Metal GPU (CPU-only for x86 Mac only) [^4] | Native Metal, "first-class citizen" [^6] | Wraps llama.cpp + MLX, both native [^11] | Purpose-built for Apple unified memory [^15] | **CPU-only, experimental** — no Metal [^19] | Native Metal via MLX backend [^22] |
| Quantization | GGUF + QAT variants (1B/4B/12B/27B) [^5] | Full GGUF K-quant family (Q4_K_M…Q8_0) [^6][^8] | Whatever llama.cpp/MLX support | Native 4/6/8-bit MLX format (not GGUF) [^16] | AWQ/GPTQ/GGUF/bnb — **none work on CPU backend** [^19] | MLX quant only; GGUF limited to non-Gemma archs [^22] |
| OpenAI-compatible API | Yes, `/v1/chat/completions` [^5] | Yes, `llama-server` [^8] | Yes, dedicated docs [^12] | Yes, `mlx_lm.server` (+ 3rd-party `mlx-omni-server`) [^17] | Yes, `vllm serve` [^19] | Yes (reuses vLLM server layer) [^22] |
| Gemma 3 12B tok/s (Mac, anecdotal) | ~15–23.5 tok/s (unverified, mixed conditions) [^2][^18] | No direct number found; proxy Llama-3-8B ≈ 34–51 tok/s on M1 Max/M3 Max [^8] | Not published | No direct 12B number found on real M-series chips [^18] | Not applicable (CPU-only, impractical) | ~4–11 tok/s reported for a 27B model at 100K context (not 12B) [^19] |

---

## Option 1: Ollama (Recommended default)

**License:** MIT, confirmed in the repo's `LICENSE` file[^1].

**Maintenance:** Latest release `v0.34.3`; release cadence shows continuous point releases (v0.33.1 → v0.34.3 across recent weeks); commit-activity API shows ~14–47 commits/week sustained; 181,491 stars, 17,972 forks, 4,061 open issues[^2][^3].

**Apple Silicon acceleration:** Official docs state macOS support requires Sonoma+ and explicitly calls out "Apple M series (CPU **and GPU** support)" vs. "x86 (CPU only)" — i.e., Metal/GPU is used natively on Apple Silicon, not just as a fallback. Release notes reference Metal-specific fixes (e.g., avoiding GPU timeouts loading from slow storage) and Apple-Silicon-specific optimizations. GPU vs. CPU placement is inspectable per-model via `ollama ps`'s `PROCESSOR` column[^4].

**Quantization:** The model library (`ollama.com/library/gemma3`) lists Gemma 3 at 1B/4B/12B/27B plus dedicated QAT (quantization-aware trained) tags (e.g., `gemma3:12b-it-qat`) that Ollama's own docs describe as preserving "similar quality as half precision (BF16) while maintaining a lower memory footprint (3x less...)"[^5].

**OpenAI-compatible API:** Confirmed — `POST /v1/chat/completions` (and `/v1/responses`) served locally at `http://localhost:11434/v1/`, with documented Python/JS/curl examples[^5].

**Benchmarks (anecdotal, caveated):** One GitHub issue reports ~23.5 tok/s for `gemma3:12b` on a Mac Mini M4 Pro (RAM unspecified, single report, no controlled methodology)[^2]. A separate thread reports ~15 tok/s for `gemma3:12b`/`4b` on an M3 Pro 36GB — but this was measured while a KV-cache-quantization bug was active (since fixed), so it likely understates current performance[^18]. No time-to-first-token figures were found for any Apple chip.

---

## Option 2: llama.cpp (+ LM Studio as GUI wrapper)

**License:** MIT[^6].

**Maintenance:** 129,222 stars, 23,594 forks, 2,536 open issues; commits within the hour of research; near-daily release cadence with detailed PR-level changelogs — one of the most actively maintained OSS ML infra projects on GitHub[^7].

**Apple Silicon acceleration:** README explicitly states Apple Silicon is "a first-class citizen — optimized via ARM NEON, Accelerate and Metal frameworks"; build docs confirm "On MacOS, Metal is enabled by default. Using Metal makes the computation run on the GPU."[^6]

**Quantization & Gemma 3 support:** Supports the full K-quant family (1.5-bit through 8-bit, including Q4_K_M/Q5_K_M/Q6_K/Q8_0)[^8]. Gemma 3 architecture support was merged via PR #12343 (merged 2025-03-12), adding a dedicated `Gemma3Model` GGUF converter for 1B/4B/12B/27B, with vision support tracked separately[^6].

**OpenAI-compatible API:** `llama-server` explicitly documents OpenAI-API-compatible chat completions, responses, and embeddings routes, plus an Anthropic-compatible endpoint. `llama serve -hf <model>` launches this server directly[^8].

**Benchmarks:** No Gemma-3-specific number could be sourced. As a same-size-class proxy (Llama 3 8B Q4_K_M via llama.cpp/Metal): M1 Max 64GB ≈ 34.5 tok/s, M3 Max 64GB ≈ 50.7 tok/s, M2 Ultra ≈ 76.3 tok/s generation[^8]. Gemma 3 12B, being a similar parameter count with a different (interleaved local/global) attention structure, would plausibly land in a broadly similar range, but this is an inference, not a citation.

### LM Studio (GUI wrapper around llama.cpp + MLX)

**License/terms:** Proprietary closed-source freeware (publisher Element Labs, Inc.); free tier is unrestricted for local model use, paid tiers add optional cloud models. The underlying inference engines (llama.cpp, MLX) remain open source; the app itself is not[^9].

**Maintenance:** Frequent dated release notes (v0.3.37 → v0.3.39 → v0.4.0), roughly weekly-to-biweekly[^10].

**Apple Silicon support:** Explicitly supports both llama.cpp and MLX backends on Mac; native support for M1–M4 chips, macOS 14+ (Intel Macs unsupported); active MLX engine development documented in dedicated blog posts[^11].

**OpenAI-compatible API:** Yes — dedicated docs cover Chat Completions, Completions, Embeddings, Models listing, Responses, Structured Output, and Tool Use, plus an Anthropic-compatible Messages API[^12].

**Benchmarks:** No official Gemma 3 tokens/sec numbers published by LM Studio were found.

---

## Option 3: MLX / mlx-lm (Recommended power-user alternative)

**License:** MIT for both MLX and mlx-lm, © Apple Inc.[^13]

**Maintenance:** MLX ~28.5K★, mlx-lm ~7.1K★ (split out of mlx-examples in March 2025); both ship every 2–6 weeks with 100+ commits/quarter; maintained by Apple's own ML research team (README: "brought to you by Apple machine learning research")[^14].

**Apple Silicon acceleration:** MLX is purpose-built for Apple's unified-memory architecture — arrays live in shared memory and operations run on any supported device without data transfer; computations are lazy/graph-optimized. This is not a Metal "port" of a CUDA-first design (unlike llama.cpp/Ollama, which added Metal as a backend) — it's designed from scratch around Apple Silicon's shared CPU/GPU memory pool[^15].

**Quantization:** Native 4-bit/6-bit/8-bit quantization via `mlx_lm.convert -q`, using MLX's own safetensors-based format (not GGUF). The `mlx-community` org on Hugging Face hosts pre-quantized Gemma 3 checkpoints at 4bit/6bit/8bit/bf16 for 1B/4B/12B/27B (no 9B exists). Multimodal variants require the separate `mlx-vlm` project[^16].

**OpenAI-compatible API:** Built-in `mlx_lm.server` implements `/v1/chat/completions` and `/v1/models`, though its own docs say "not recommended for production." The third-party `mlx-omni-server` offers a fuller OpenAI+Anthropic-compatible server and has been tested against `mlx-community/gemma-3-1b-it-4bit-DWQ`[^17].

**Benchmarks:** No credible, size-matched (12B) number was found for a real M1–M4-family MacBook Pro chip. One figure citing "M5 Max" for a 27B model was found but is unverifiable against any real Apple chip and is excluded from this report's conclusions[^18]. Simon Willison's qualitative comparison (27B QAT model) found MLX used less RAM (~15GB) than Ollama (~22GB) and "feels a little faster," but published no tok/s numbers[^18].

---

## Option 4: vLLM (Not recommended for this use case)

**License:** Apache 2.0[^19].

**Maintenance:** Extremely active — 92,445 stars, 22,529 forks, 8,343 open issues, releases roughly every 2 weeks[^20].

**Apple Silicon / macOS support:** vLLM's core is CUDA/ROCm/TPU-first. Mainline macOS support is an **experimental, CPU-only** backend (FP32/FP16 only, no quantization kernels, no Metal/GPU acceleration), requiring a from-source build. A long-open GitHub feature request for Metal support (#19073, opened June 2025) remains unresolved in vLLM core[^19].

A separate, actively developed plugin — **`vllm-project/vllm-metal`** — does add genuine Metal/GPU acceleration via an MLX backend, reusing vLLM's OpenAI-compatible server/scheduler. It's promising but young (first release April 2026), and its GGUF support explicitly excludes Gemma 3 (Gemma 3 must be served via MLX-native quantized checkpoints instead)[^22].

**Quantization:** AWQ/GPTQ/GGUF/bitsandbytes are supported in mainline vLLM but **none of these quant kernels work on the CPU backend**[^19].

**OpenAI-compatible API:** Yes, `vllm serve` exposes `/v1/completions`, `/v1/chat/completions`, `/v1/responses`, `/v1/embeddings`[^19].

**Benchmarks:** No credible tok/s reports exist for mainline CPU-only vLLM on Mac in the 9-12B range. On `vllm-metal`, a 27B model at 100K context reported single-sequence decode of only ~4.25–11.2 tok/s, with the project itself flagging known performance gaps[^19].

**Conclusion:** Mainline vLLM is not realistic for this use case. `vllm-metal` is worth watching but is not yet a battle-tested choice; a native MLX runtime (`mlx-lm`) or Ollama is the simpler, more mature path today.

---

## Pydantic AI Integration Sketch

Pydantic AI treats local OpenAI-compatible servers the same way it treats Azure OpenAI: both go through `OpenAIChatModel`, just with a different `Provider` (`OllamaProvider`/`OpenAIProvider(base_url=...)` vs. `AzureProvider`)[^23].

### Azure OpenAI (current setup, for comparison)
```python
from pydantic_ai import Agent
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.azure import AzureProvider

azure_model = OpenAIChatModel(
    "gpt-4o",  # your Azure deployment name
    provider=AzureProvider(
        azure_endpoint="https://your-resource.openai.azure.com/openai/v1/",
        api_key="your-api-key",
    ),
)
```

### Local Ollama running Gemma 3 (drop-in alternative)
```python
from pydantic_ai.models.ollama import OllamaModel
from pydantic_ai.providers.ollama import OllamaProvider

local_model = OllamaModel(
    "gemma3:12b",
    provider=OllamaProvider(base_url="http://localhost:11434/v1"),
)
```

### Fallback pattern: try local first, fall back to Azure on failure
```python
from pydantic_ai.models.fallback import FallbackModel

model = FallbackModel(local_model, azure_model)  # tries local_model, falls back to azure_model
agent = Agent(model)
```
(`FallbackModel` accepts a `fallback_on` argument to control which exceptions trigger the next model — defaults to `ModelAPIError`.)[^23]

### Important caveat before wiring this into `invitations_manager.py`/`inbox_manager.py`

Both scripts rely on Pydantic AI's structured-output/function-calling to make accept/ignore/urgency decisions. Multiple sources confirm Gemma 3's tool-calling and structured-output support through OpenAI-compatible APIs is **less reliable** than larger frontier models:
- Pydantic AI's own docs note that custom `base_url` endpoints may need a manual `OpenAIModelProfile` override (e.g., `openai_chat_supports_multiple_system_messages=False`), explicitly calling out Gemma as one of the affected model families[^23].
- Open GitHub issue: "Support 'prompted tool calls' for models that don't have native support (e.g. Ollama + Gemma3)" — reports Gemma3 tool/MCP calls failing where Llama succeeds[^24].
- Open GitHub issue: `gemma-3-27b-it` via OpenRouter fails all three structured-output strategies (tool-based, JSON mode, prompted)[^25].

**Recommendation:** before adopting Gemma 3 as a fallback for these two scripts, run the existing eval suite (`evals.py`, `linkedin_invitation_cases.yaml`) against the local model to confirm the accept/ignore/undecided decision schema is reliably produced — this is the single biggest integration risk, independent of which serving framework is chosen.

---

## Recommendation Summary

1. **Primary recommendation: Ollama.** MIT license, very active maintenance, native Metal acceleration, GGUF+QAT quantized Gemma 3 12B readily available, built-in OpenAI-compatible API, and a dedicated first-class `OllamaProvider` in Pydantic AI with documented code samples — the lowest-friction integration path.
2. **Power-user alternative: MLX/mlx-lm.** Apple's own unified-memory-native framework, likely to extract more tokens/sec and lower memory footprint from the same M-series chip since it isn't a CUDA-first design retrofitted with a Metal backend; slightly more integration work (needs `mlx-omni-server` or `mlx_lm.server` for OpenAI compatibility, and mlx-lm's own server explicitly says "not recommended for production").
3. **LM Studio** is a reasonable GUI-first option if a non-technical team member needs to manage models, but its proprietary licensing (vs. fully open Ollama/llama.cpp) is a consideration.
4. **Avoid vLLM** for this use case — its Mac story is either CPU-only/impractical (mainline) or an early-stage plugin (`vllm-metal`) not yet proven for Gemma 3 at this scale.
5. **Before committing**, run `ollama run --verbose gemma3:12b` (or `mlx_lm.generate --verbose`) directly on the target MacBook Pro to get real tok/s and TTFT numbers — no source found during this research gave a controlled, size-matched benchmark for Gemma 3 12B on M-series MacBook Pro hardware specifically, and use `evals.py` to validate structured-output reliability before deploying as a fallback.

---

## Footnotes

[^1]: Ollama LICENSE file (MIT) — https://raw.githubusercontent.com/ollama/ollama/main/LICENSE
[^2]: Ollama GitHub repo stats & release notes — https://github.com/ollama/ollama/releases/tag/v0.34.3 ; https://github.com/ollama/ollama/releases ; benchmark anecdote https://github.com/ollama/ollama/issues/10913
[^3]: Ollama commit activity & repo metadata — `https://api.github.com/repos/ollama/ollama` and `https://api.github.com/repos/ollama/ollama/stats/commit_activity` (queried 2026-09-22)
[^4]: Ollama macOS docs — https://docs.ollama.com/macos ; FAQ (`ollama ps` PROCESSOR column) — https://docs.ollama.com/faq
[^5]: Ollama Gemma 3 model library — https://ollama.com/library/gemma3 ; OpenAI compatibility docs — https://docs.ollama.com/api/openai-compatibility.md
[^6]: llama.cpp LICENSE — https://github.com/ggml-org/llama.cpp/blob/master/LICENSE ; README (Apple Silicon "first-class citizen") — https://github.com/ggml-org/llama.cpp ; build docs (Metal default on macOS) — https://github.com/ggml-org/llama.cpp/blob/master/docs/build.md ; Gemma 3 support PR — https://github.com/ggml-org/llama.cpp/pull/12343
[^7]: llama.cpp repo metadata — `https://api.github.com/repos/ggml-org/llama.cpp` ; releases — https://github.com/ggml-org/llama.cpp/releases
[^8]: llama.cpp quantization docs — https://github.com/ggml-org/llama.cpp/blob/master/tools/quantize/README.md ; server/OpenAI-compat docs — https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md ; proxy benchmark data — https://github.com/XiongjieDai/GPU-Benchmarks-on-LLM-Inference
[^9]: LM Studio Terms of Service — https://lmstudio.ai/app-terms ; Pricing — https://lmstudio.ai/pricing
[^10]: LM Studio blog/changelog — https://lmstudio.ai/blog
[^11]: LM Studio system requirements — https://lmstudio.ai/docs/app/system-requirements ; MLX engine blog — https://lmstudio.ai/blog/mlx-engine-agentic-workloads
[^12]: LM Studio OpenAI compatibility docs — https://lmstudio.ai/docs/developer/openai-compat ; 0.4.0 release notes — https://lmstudio.ai/blog/0.4.0
[^13]: MLX LICENSE — https://raw.githubusercontent.com/ml-explore/mlx/main/LICENSE ; mlx-lm LICENSE — https://raw.githubusercontent.com/ml-explore/mlx-lm/main/LICENSE
[^14]: MLX repo — https://github.com/ml-explore/mlx ; mlx-lm repo — https://github.com/ml-explore/mlx-lm ; mlx-examples repo — https://github.com/ml-explore/mlx-examples
[^15]: MLX docs (unified memory, lazy computation) — https://ml-explore.github.io/mlx/build/html/index.html
[^16]: mlx-lm README (quantization) — https://github.com/ml-explore/mlx-lm ; HF mlx-community Gemma 3 checkpoints — https://huggingface.co/mlx-community/gemma-3-12b-it-4bit , https://huggingface.co/mlx-community/gemma-3-27b-it-4bit , https://huggingface.co/mlx-community/gemma-3-4b-it-4bit
[^17]: mlx-lm server docs — https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/SERVER.md ; mlx-omni-server — https://github.com/madroidmaq/mlx-omni-server
[^18]: MLX/Ollama Gemma 3 benchmark anecdotes — https://github.com/Blaizzy/mlx-vlm/issues/1920 (unverified "M5 Max" figure, excluded from conclusions) ; https://github.com/ollama/ollama/issues/9683 (M3 Pro 36GB, ~15 tok/s during KV-cache-quant bug, fixed in PR #12245) ; Simon Willison qualitative comparison — https://simonwillison.net/2025/apr/19/gemma-3-qat-models/
[^19]: vLLM LICENSE — https://github.com/vllm-project/vllm/blob/main/LICENSE ; CPU/macOS install docs — https://docs.vllm.ai/en/latest/getting_started/installation/cpu/ ; Metal feature request (open) — https://github.com/vllm-project/vllm/issues/19073 ; Apple Silicon build issues — https://github.com/vllm-project/vllm/issues/28352 , https://github.com/vllm-project/vllm/issues/34351 ; quantization hardware matrix — https://docs.vllm.ai/en/latest/features/quantization/ ; OpenAI-compatible serving docs — https://docs.vllm.ai/en/latest/serving/online_serving/
[^20]: vLLM repo metadata & releases — https://github.com/vllm-project/vllm/releases
[^21]: vllm-metal repo — https://github.com/vllm-project/vllm-metal
[^22]: vllm-metal docs — https://docs.vllm.ai/projects/vllm-metal/en/latest/ ; GGUF support matrix — https://docs.vllm.ai/projects/vllm-metal/en/latest/gguf/ ; performance issue — https://github.com/vllm-project/vllm-metal/issues/713 ; bandwidth gap issue — https://github.com/vllm-project/vllm-metal (issue #695)
[^23]: Pydantic AI models overview — https://ai.pydantic.dev/models/ ; OpenAI-compatible models guide — https://ai.pydantic.dev/models/openai/#openai-compatible-models ; Ollama-specific docs — https://ai.pydantic.dev/models/ollama/ ; Azure AI Foundry docs — https://ai.pydantic.dev/models/openai/#azure-ai-foundry ; custom OpenAI client pattern — https://ai.pydantic.dev/models/openai/#custom-openai-client ; FallbackModel API reference — https://ai.pydantic.dev/api/models/fallback/
[^24]: Pydantic AI issue — prompted tool calls for Ollama + Gemma3 — https://github.com/pydantic/pydantic-ai/issues/2170
[^25]: Pydantic AI issue — Gemma structured output failures via OpenRouter — https://github.com/pydantic/pydantic-ai/issues/2976 ; related — https://github.com/pydantic/pydantic-ai/issues/2800
