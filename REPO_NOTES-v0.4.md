# REPO_NOTES v0.4 — pi audit for TS agent + iteris Tier-5 patterns (parked)

Date: 2026-09-04. Reference clones: `pi-main/` (MIT, Mario Zechner 2025 —
verified `pi-main/LICENSE`) and `iteris-main/` (Apache-2.0 — NOT MIT as
assumed; still permissive, attribution required if vendored).

## 1. pi-main — @earendil-works/pi-mono (TypeScript, Node ≥22, npm workspaces)

### Language / framework / entry point
- TS 5.9 monorepo, `pi-main/package.json` workspaces `packages/*`.
- Entry: `packages/coding-agent/src/main.ts` (CLI parse → `createAgentSession()`);
  bin `pi` → `dist/bundle/cli.js`. TUI via `packages/tui`, RPC via
  `packages/protocol` (CBOR framing) + `packages/client`/`server`.

### Agent loop
- `packages/agent/src/agent-loop.ts` + `harness/` (`agent-harness.ts`,
  `reducer.ts`, `system-prompt.ts`, `events.ts`): turn loop with steering
  messages, tool-call batching (sequential/parallel per tool), `beforeToolCall`
  (block/terminate) and `afterToolCall` hooks, truncation guard
  (`failToolCallsFromTruncatedMessage`). This is where the card-confirmation
  gate will live (harness-level enforcement, not prompt).
- Subagent machinery (`harness/session/`, skills, compaction) ships as-is;
  unused in v1 (future parallel workers).

### Providers (`packages/ai`)
- `src/models.ts` (`createModels`/`createProvider`), `src/providers/*.ts`
  per-vendor adapters, `src/auth/` (api-key + OAuth, credential store),
  `src/api/*` per-API streams, `calculateCost`, thinking-level maps.
- `Context` = systemPrompt + messages + tools; `streamSimple`/`complete`
  convenience; per-request `signal` abort propagates.
- Verdict: BORROW the adapter pattern + auth-resolution shape for A4
  (config.toml single truth), reimplemented against our config schema —
  do NOT fork pi-ai wholesale; minimize diff for upstream merges.

### Tools
- `packages/coding-agent/src/core/tools/` (bash 18K, read, edit, write,
  grep, find, ls) + `packages/agent/src/harness/tools/`. Tool = schema +
  prepare/execute/finalize + `executionMode`. Math tools
  (`killcheck_encode/run`, `panel_review`) sit alongside via pi's native
  tool mechanism; nothing removed.

### Hooks / sessions / TUI
- Hooks: `beforeToolCall`/`afterToolCall`, steering/follow-up polling,
  compaction — extension points for the gate + panel attribution.
- Sessions: `packages/session-backends/sqlite-node` + `agent-session*.ts`
  (117K); chats are NOT journal events (rule unchanged).
- TUI: `packages/tui/src/` (components, layout, keybindings, terminal) —
  used as-shipped; Ramanujan renders cards/panel rows as TUI components.

### Borrow verdicts (pi)
| Item | Verdict | Note |
|---|---|---|
| Provider adapters + auth resolve | BORROW (adapt, MIT headers intact) | A4, against config.toml |
| Agent loop + harness hooks | BORROW (minimal diff) | A5 gate lives here |
| Tool mechanism | BORROW | math tools as native tools |
| TUI | BORROW as-shipped | brand strings → Ramanujan |
| Session storage | BORROW as-shipped | chats ≠ journal |
| Subagents/compaction | PATTERN (defer, unused v1) | future workers |
| Model catalog refresh | IGNORE | our pins are verbatim |
| OAuth flows | IGNORE | env/stored keys only |

## 2. iteris-main — Tier-5 patterns (AUDIT + PARK, nothing implemented)

- `src/iteris/tasks.py` (TASK_POOL.json, file-locked task frontier),
  `memory/facts.py` (fact frontmatter + FACT_INDEX), `events.py` (JSONL
  envelope), `executors.py` (codex/claude shell-out), `family.py`/`evolve.py`
  (generalization families). License Apache-2.0.
- Verdict: PATTERN only — task pool → future Tier-5 decomposition,
  fact index → future reliability table shape, families → future
  generalization. Nothing wired in v0.4. No vendoring (license delta moot).

## 3. ADR (recorded in BUILDLOG v0.4 A1)
- Layout: Python engine at repo root (frozen) + `agent/` TS workspace
  copied from pi (`agent/packages/*`, headers/LICENSE verbatim, brand →
  Ramanujan, internal package names stay for merge-ability).
- Bridge: `ramanujan-engine {encode,check,verify,replay} --json` (only new
  CLI); contract doc `agent/docs/bridge.md`; TS codes against doc.
- Rename: Python script `ramanujan` → `ramanujan-engine`; TS bin owns
  `ramanujan` (npm link dev, single-binary engine bundling deferred).
- Diff discipline: pi files modified vs intact listed in BUILDLOG A2;
  MIT/Apache headers + LICENSE files preserved verbatim.
