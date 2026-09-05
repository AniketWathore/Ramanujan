# REPO_NOTES — Task 0 audit of reference repos

Date: 2026-09-02
Location of clones: `iteris-main/` and `pi-main/` as siblings of this project root.

## 1. iteris (../iteris-main) — frenzymath/iteris 0.2.0

### Language / framework / entry point
- **Language:** Python 3.10+ (declared `>=3.10`, used with 3.12 in practice), `setuptools` layout under `src/`.
- **Framework stack:** `typer`/`click` + `rich` for CLI, `fastapi`/`uvicorn` for dashboard, `pydantic>=2` for config, `pdfminer`, `requests`. Dashboard UI is React+TS (Fastify server).
- **Entry point:** `iteris = "iteris.cli:app"` (`src/iteris/cli.py` dispatching to `src/iteris/commands/`), with `src/iteris/project.py:init_project` as the project scaffolder. Main runtime surfaces: `iteris monitor` (interactive), `iteris run` (Codex/Claude loop), `iteris dashboard`.

### LLM-call abstraction
- **No direct LLM HTTP provider abstraction.** `src/iteris/executors.py` is the abstraction — it resolves an *executor* (`codex` vs `claude`) and builds shell commands (`build_codex_headless_command`, `build_claude_headless_command`) plus env (`main_agent_home_env`, `headless_home_env`, `resolve_agent_model`). Actual inference is delegated to the external `codex` / `claude` CLIs via `codex exec --json -` or `claude -p --output-format stream-json`. No token/cost/latency logging here; capture is via JSONL event logs on stdout.
- **Worth borrowing?** Pattern only. The executor abstraction is too shell-coupled for Ramanujan, which needs direct HTTP provider calls with cost accounting. Borrow the **env-var-driven model override** (`ITERIS_*_MODEL` / `CODEX_MODEL`, `ITERIS_CLAUDE_*_MODEL`) and the **per-run home isolation** (`CODEX_HOME`/`CLAUDE_CONFIG_DIR`) concept for reproducibility, but reimplement as a tiny typed provider spec (our `VerifierSpec`) — do not reuse code.

### File schemas / event formats
- **Events:** `src/iteris/events.py` writes `{schema_version:"iteris.event.v0", event_id, event_type, created_at, project_path, payload}` via `project.append_jsonl` (compact JSON, one object per line) to `.iteris/logs/events.jsonl`. Append-only JSONL is already the pattern we need.
- **Tasks:** `src/iteris/tasks.py` owns `tasks/TASK_POOL.json` (schema `iteris.task_pool.v0`) with file locking (`fcntl.flock`), atomic writes via `tempfile.mkstemp` + `os.replace`, and a `TASK_POOL.lock`. Legacy also uses `TASK_BOARD.jsonl`.
- **Facts:** `src/iteris/memory/facts.py` validates YAML frontmatter (`fact:`, `predecessors`, `status` in `{draft,submitted,reviewed,verified,rejected}`) and maintains a derived `FACT_INDEX.jsonl` (rebuilt from facts).
- **Artifacts:** `project.py:write_json` / `append_jsonl` are atomic (tempfile+replace) — good hygiene.
- **Worth borrowing?** PATTERN + small BORROW:
  - **BORROW** the atomic tempfile+replace write (`project.py:121-138`) and the compact `separators=(",",":")` JSONL append — we will copy that idiom into `ramanujan/journal.py` single-write path.
  - **PATTERN** the event envelope (`schema_version`, `event_id`/`ts`, `event_type`/`type`, `payload`) and the “append-only source of truth, derived views regenerate” discipline — matches our frozen `journal.jsonl` design but we must **not** reuse their field names verbatim (we freeze `ts/run_id/type/payload`).
  - **IGNORE** the task-pool locking complexity for this slice (single writer library, no daemon). Also ignore fact frontmatter/YAML — Ramanujan facts are JSON/pydantic.

### Verdict
**PATTERN** — do not import. Borrow exactly two patterns: atomic JSON(L) writes and the JSONL event-log discipline. Everything else (executor shell-out, task-pool schema, fact frontmatter) is IGNORE for Slice 1.

---

## 2. pi (../pi-main) — earendil-works/pi-mono 0.0.3

### Language / framework / entry point
- **Language:** TypeScript 5.9, Node >=22.19, monorepo via npm workspaces.
- **Packages:** `@earendil-works/pi-ai` (multi-provider LLM API), `@earendil-works/pi-agent-core` (agent runtime), `@earendil-works/pi-coding-agent` (CLI), `@earendil-works/pi-tui`. Build with `esbuild`, `tsgo`, `biome`.
- **Entry point:** `packages/coding-agent/src/index.ts` → `packages/agent/src/agent.ts` + `agent-loop.ts`; provider dispatch via `packages/ai/src/models.ts:createModels` / `createProvider`.

### LLM-call abstraction
- **Core:** `packages/ai/src/models.ts` defines `Provider<TApi>` (id/name/baseUrl/auth/getModels/refreshModels/stream/streamSimple) and `Models` collection (provider registry, auth resolution, `stream`/`complete`). `createProvider` merges baseline+dynamic model lists and dispatches on `model.api`. Concrete providers in `packages/ai/src/providers/*.ts` (e.g. `anthropicProvider()` in `anthropic.ts`) declare `api: anthropicMessagesApi()` plus auth (`ApiKeyAuth` with `env` fallbacks `ANTHROPIC_API_KEY_ENV` etc., plus OAuth via `credential-store`).
- **Details worth noting:**
  - Auth is provider-scoped with `AuthContext`/`CredentialStore`, supports api-key + OAuth, source labels (`source:"stored credential"` vs env name), and `getAuth(model)` header merging (`mergeHeaders`).
  - Request path: `ModelsImpl.applyAuth` → `provider.stream(model, context, options)` → `AssistantMessageEventStream` (async iterable, typed `AssistantMessageEvent`).
  - Cost: `calculateCost(model, usage)` and per-tier `ModelCostRates`; thinking levels (`ThinkingLevel`, `getSupportedThinkingLevels`, `clampThinkingLevel`).
  - Logging/retries: refresh has generation+AbortController, publication chains, `raceWithAbortSignal`; per-request `signal` abort propagates; no explicit retry wrapper — left to caller.
- **Worth borrowing for `providers.py`:**
  - **PATTERN** the typed `Provider` + `VerifierSpec` separation, `stream`/`complete` convenience, env-var-driven auth with `source` labels, and `hasApi` type guard are excellent design — we will mirror them in a much smaller Python form: a frozen `VerifierSpec` (pydantic, pinned `model_id`/`provider`/`family`/`role`/`temperature`/`max_output_tokens`), `call_llm(spec, messages)` with retries, token/cost/latency capture, and `env`-only keys. Do **not** port the TS generics or model catalog refresh — keep it boring.
  - **BORROW** the header-merge idea for model snapshot pinning (never alias) and the `calculateCost`-style per-model rate table (defer exact rates to Slice 2; log 0-cost for now if unknown).
  - **IGNORE** the npm model catalog generation (`scripts/generate-models.mjs`, `models.generated.ts`) and OAuth flow — env-var keys only per frozen spec.

### Tool-call loop / session handling
- **`packages/agent/src/agent-loop.ts`** (~803 lines): `agentLoop` / `runAgentLoop` → `runLoop` (outer: steering/follow-ups; inner: tool calls). Converts `AgentMessage[]` → `Message[]` only at boundary (`convertToLlm`), builds `llmContext={systemPrompt,messages,tools}`, resolves api key per turn (`getApiKey`), streams via `streamFunction(config.model, llmContext, {...config, apiKey, signal})`.
  - Streaming: `EventStream<T,R>` in `ai/src/utils/event-stream.ts` (queue+waiters, `push`/`end`/`result()`), yielding `message_start/update/end`, `tool_execution_*`, `turn_start/end`, `agent_end` with `hasMoreToolCalls` loop and truncated-`length` guard (`failToolCallsFromTruncatedMessage`).
  - Tool execution: `executeToolCalls` dispatches to `executeToolCallsSequential` vs `parallel` (per-tool `executionMode`), with `prepareToolCall` (validate, `beforeToolCall` block), `executePreparedToolCall` (collect `partialResult`), `finalizeExecutedToolCall` (`afterToolCall` hook), and `shouldTerminateToolBatch`.
- **Worth borrowing:**
  - **PATTERN** the single boundary conversion + `signal`-aware streaming + truncation guard — conceptually valuable for Slice 3+ orchestration but out of scope for Slice 1 (no tool loop needed for kill-check). For now, log the pattern in `AGENTS.md` as future reference; do not implement an agent loop.
  - **IGNORE** the steering/follow-up message polling (`getSteeringMessages`, `getFollowUpMessages`, `prepareNextTurn`, `transformContext`) and the whole `EventStream` machinery — Ramanujan Slice 1 uses a trivial encode→search→verify loop with journal events, not an agent harness.

### File schemas / event formats
- No file-based JSONL event schema like iteris; pi leans on in-memory `EventStream` + optional persistence via `session-backends/sqlite-node`. Session/tool messages are typed (`AgentMessage`, `AssistantMessage`, `ToolResultMessage` with `addedToolNames`, `timestamp`).

### Verdict
**PATTERN** for provider abstraction, **IGNORE** for agent-loop/session handling in this slice.
- **BORROW (adapted):** pinned `model_id` spec, env-only keys, header/auth merge, cost/latency capture shape, and the `stream→result()` idiom — reimplemented in ~100 LOC Python, not imported.
- **PATTERN (deferred):** `runLoop`'s trunk guard (fail truncated tool calls) and `before/afterToolCall` hooks inspire our encoder's validation-retry loop and `verify.py`'s independent re-check.
- **IGNORE:** full TS harness, model catalog refresh, OAuth, TUI, session backends.

---

## 3. Summary decision table

| Subsystem | iteris verdict | pi verdict | Ramanujan Slice 1 action |
|---|---|---|---|
| Project layout & atomic I/O | **BORROW** `project.py:write_json`/`append_jsonl` tempfile+replace + JSONL append | — | Implement in `ramanujan/journal.py` single write path; no file locks yet. |
| Event envelope & sourcing | **PATTERN** (`iteris.event.v0` envelope, derived `FACT_INDEX` regen) | Pattern (`EventStream`) but in-memory | Freeze `ramanujan` envelope `{ts,run_id,type,payload}` per §4; journal.jsonl is source of truth. |
| Task pool / facts / family | **IGNORE** (TASK_POOL, frontier, FACT frontmatter) | — | Not in Slice 1; schemas defined but lightly used. |
| LLM provider abstraction | **IGNORE** (shell executor) | **PATTERN→BORROW (mini)** `createProvider`/`Models`/`Provider`/`calculateCost` | `ramanujan/providers.py`: tiny `VerifierSpec` + `call_llm` with retries, pinned snapshot IDs, cost/latency logging to journal. |
| Tool-call loop / session | — | **IGNORE** (defer) | No loop in Slice 1; kill-check is `runner.py` encode→search→verify. Encode retry feeds validation error (analogous to pi's `length` guard). |

## 4. Concrete borrow list (what actually enters Ramanujan code)

1. **Atomic JSON(L) write idiom** (iteris `project.py:121-144`) → `ramanujan/journal.py` writer (single module touching journal).
2. **Compact JSONL separators** `separators=(",",":")` for journal lines (iteris `append_jsonl`) — readability irrelevant, greppability matters.
3. **Env-var-only keys never in files** (both repos do this; pi's `ANTHROPIC_API_KEY_ENV` family) → `ramanujan/encoder.yaml` + `providers.py` enforce `os.environ` only.
4. **Pinned snapshot IDs, cost/latency on every call** (pi `calculateCost`, `model.id` vs alias) → journal `llm_call` payload carries `model_id`, `tokens`, `cost`, `latency_ms`, `source`.
5. **Validation-error-fed retry** (pi's truncated-tool-call fail + iteris pattern of doing nothing silently) → `ramanujan/encoder.py` retry ≤3 with pydantic error echoed to LLM.

Everything else is reference-only. No runtime dependency on either repo; no code import.

---

## 5. Risks / gotchas surfaced

- `iteris` assumes `fcntl` file locking (macOS/Linux only) — Ramanujan avoids by single-write-path until daemon slice.
- `iteris` per-run `CODEX_HOME`/`CLAUDE_CONFIG_DIR` symlink trick can diverge on rename — hints to prefer explicit `run_id` + env fingerprint in journal rather than filesystem tricks.
- `pi`'s `Model.thinkingLevelMap` / `cost.tiers` complexity is overkill for Slice 1; defer.
- Both repos send full project context to providers — Ramanujan encoder prompt must be minimal (statement + DSL spec only) to stay within budget and avoid leaking journal.

---

*End of Task 0 audit. STOP for human review before Task 1 scaffold.*
