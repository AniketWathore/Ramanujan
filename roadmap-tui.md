# Ramanujan TUI-only roadmap (`roadmap-tui.md`)

Goal: `ramanujan` behaves like `pi` or any coding agent — install, launch,
setup wizard, ASCII home + chat box, normal chatbot talk, research pipeline
when asked. **No commands, ever.** No `uv run …` spam in the transcript, no
raw JSON dumps, no `/card` `/runs` menus. Every stage ends in an interactive
checkpoint (confirm / continue / type-your-response, Claude-Code style).

Companion: `roadmap.md` (v2 engine phases, done). This file is the TUI-only
refactor on top. New file — does not replace `roadmap.md`.

## 0. What exists today (verified in repo, not assumed)

**Python engine — HAVE, keep as-is (single writer `ramanujan/journal.py`):**
- `problem_spec.py` — Initialiser → `problem_spec.json` (statement, domain,
  variables, objective, known cases, open questions; `statement_formal: null`
  at Stage 1). This is the structured store the user asked for — **not** a ClaimCard.
- `literature.py` — papers index entries carry `source_url` or explicit
  `"model-memory, unverified"`.
- `orchestrator.py` — N worktrees, per-worktree budget, stall detection,
  progress reports, local journals + compaction, contradiction flagging.
- `questions.py` — micro question queue, `worktree_id` nullable
  (orchestrator-level uses the same pattern), timeout defaults surfaced at
  Checkpoint C.
- `claims.py` — claims board folds to latest per `claim_id` over the journal.
- `checkpoint.py` — one generic Checkpoint abstraction for all stages.
- `consolidation.py` — independent re-execution + toolchain pinning.
- `reviewer.py` — summary + appendix (failed approaches included) → `report_final.md`.
- `panel_service.py` — §2 authority routing (`tier0 | tier2-verdict | tier2-advisory-only`),
  different-family exclusion via `family_registry.json`.
- `presets.py` + `families.py` — named presets, deadlock guard (warn, never block).
- `reliability.py`, `budget.py`, `taxonomy.py`.
- `tests/` — 30+ files covering all of the above.

**Bridge (`agent/packages/bridge/`) — HAVE, keep:**
spawns the engine binary directly via `execFile` (`resolveEngineBin`: explicit
opt → `RAMANUJAN_ENGINE_BIN` → `<cwd>/.venv/bin/ramanujan-engine` → PATH).
**Never uses `uv run`.** Covers initialise, literature, spawn-worktree,
post-claim, post-question, checkpoint-C, request-panel, consolidate, review,
replay. The `Uninstalled/Installed` spam in the transcript is **not** the
bridge — it is the agent falling back to bash `uv run` (see §2).

**TS config (`agent/packages/config/`) — HAVE, extend:**
providers, roles incl. `main_model`, `presets.ts`, `families.ts`, headless
`onboarding.ts` helpers (add-provider → live `/models` → assign roles).

**TUI substrate (vendored pi) — HAVE, build on:**
selector components (`model-selector`, `oauth-selector`, `settings-selector`,
`tree-selector`, …), `first-time-setup.ts`, CLI `startup-ui.ts`
(`shouldRunFirstTimeSetup`), extension UI primitives
(`select | confirm | input | notify` in `core/extensions/types.ts`).

## 1. Gaps (what is missing — nothing here is assumed)

1. **First-launch setup wizard (TUI).** `onboarding.ts` handles only
   `assistant/encoder/panel`, is headless-only, and was never bound to the TUI
   (binding "deferred to A5", never landed). Missing: `main_model` setup,
   provider+model pool for the computational section, preset creation for N
   subagents (preset or manual provider/model multi-pick). Must trigger
   automatically when config is empty, before the ASCII home screen.
2. **Stage tools in the TUI extension.** `agent/packages/math-tools/src/extension.ts`
   currently registers **zero tools and zero commands** (only prompt hooks).
   With no tools, the agent shells out through pi's `bash` tool
   (`uv run ramanujan-engine …`) — that is the spam + raw JSON. Must register:
   `initialise`, `literature_search`, `spawn_worktrees`, `post_claim`,
   `request_panel`, `consolidate`, `review` — all via bridge (direct spawn).
3. **Web tool for Literature.** Correction to the brief: **pi has no web tool**
   (`core/tools/` = read, bash, powershell, edit, write, grep, find, ls only).
   There is nothing to copy verbatim. Must build a new `web_fetch`
   (URL → markdown/text, timeout, size cap, journal-safe) in math-tools +
   tests, and offer it to the Literature stage.
4. **Interactive checkpoints.** Per stage: show structured output
   (spec / synthesis+examples / worktree table / fact set / report) → user
   picks **confirm-and-continue / revise / type-your-response**
   (Claude-Code style). Primitives exist (`select/confirm/input/notify`,
   selector components); the checkpoint cards + question-queue rendering do not.
5. **Chat-vs-research routing.** Normal chat stays a chatbot; research intent
   ("check this conjecture", "prove X", "help with …") starts
   Initialiser → `problem_spec.json`. Needs a system-prompt dispatch rule +
   session artifact (`problem_spec.json` shown to user, passed to Literature
   as a file, never a ClaimCard).
6. **Killcheck encoder off the critical path.** Per user decision (Option 1):
   the initial problem is stored as `problem_spec.json`, never a ClaimCard.
   Keep Tier0 (`claimcard.py` + `killcheck/`) **only** as the worktree-internal
   lemma checker (already its design: Tier0 inline per worktree). Remove any
   remaining gate that forces the initial problem through the encoder.
7. **Installable package.** Verify/fix the `ramanujan` bin install story
   (`npm link` today; decide: `npm pack` vs bundled binary) and engine
   discovery for non-repo installs (bridge already handles `.venv`/PATH;
   installer must guarantee one of them — no `uv run`, no `uv sync` at TUI
   runtime).
8. **Menu hygiene.** Confirm `/card` `/runs` etc. stay gone (extension
   registers no commands today — keep it that way; verify after each phase).

## 2. Build order

- **Phase T0 — Setup wizard. DONE (2026-09-06, uncommitted).**
  Mirrors pi's `/login` → `/models` exactly, writes Ramanujan config:
  1. provider picker from pi-ai's catalog (`builtinProviders()`, api-key
     capable only — **no base_url / family / id questions**; family = provider id),
  2. API key only (env var preferred so it never touches the screen),
  3. main model picker from the **live** `/models` fetch with that key
     (static catalog fallback, then manual slug),
  4. computational pool: **"use existing providers"** (pick provider → fetch →
     multi-pick models, same/different providers) or **"add new provider"**
     (same key flow), loop until Done,
  5. confirm pool → save as `default` preset (deadlock warning shown, never
     blocking) → optionally more named presets,
  6. final confirm → ASCII home + chat.
  Code: `onboarding.ts` (`main_model` role, `onboardSavePreset`,
  `needsSetupWizard` gate — headless-tested in `onboarding.test.ts`, 18 pass);
  `cli/ramanujan-setup.ts` (wizard, cancel-safe); hooked in `main.ts` next to
  pi's first-time setup (which never fires for forks). Verified in the shipped
  50-file bundle. Key input echoes (pi's input has no mask); wizard copy steers
  to env vars. Pre-existing breakage noted, not touched: coding-agent vitest
  can't run here (`agent/vitest.base.ts` missing from repo).
- **Setup fixes v2 (2026-09-06, uncommitted).** (a) Banner printed ONCE at
  wizard start (was: before every step). (b) Pool screen always shows Done
  footer (was missing until first pick). (c) Type-to-filter in selectors
  (`searchable` opt: prefix match, Backspace clears, arrows navigate; pi
  default unchanged incl. k/j aliases). (d) Full model lists + manual slug
  entry everywhere (nemotron-class models reachable). (e) Main model ALSO
  written to pi auth + persisted default — footer shows `(provider) model`
  and chat uses it; `/model` still switches anytime. Root cause of the
  anthropic fallback: provider-prefix stripping vs pi's org/model catalog ids
  — removed, ids stored verbatim. Verified headlessly + full gates green.
- **Setup fixes v3 (2026-09-06, uncommitted).** (a) Chat default clobbered:
  the pool "add new provider" branch called `wireChatModel` with that
  provider's FIRST model, overwriting the main-model pick — hence the footer
  flipping to e.g. `openrouter/aion` whenever >1 provider was added (single
  provider worked because the branch never ran). Removed: chat default is now
  written exactly once, from the step-3 main-model pick. (b) fd/rg
  "Downloading…" spam: `showManagedToolStatus` returns early unless warning —
  downloads still run in background, failures still surface. Gates green
  (pytest 153, ruff, bridge 20 / config 18 / math-tools 33, 50-file bundle).
- **Independence from pi (2026-09-06, uncommitted).** Root cause of both
  reported issues: the fork kept pi's identity — `piConfig.configDir: ".pi"`
  (→ shared `~/.pi/agent`: auth.json, settings.json/default model, sessions)
  plus a global `pi` bin from `npm link`, so opening `pi` booted OUR bundle
  and our wizard wrote into pi's settings (hence the foreign footer model
  `openrouter/aion-labs/aion-2.0` from `~/.pi/agent/settings.json`). Fixed:
  `configDir: ".ramanujan"` (own `~/.ramanujan/agent`, auth, settings,
  sessions; `RAMANUJAN_CODING_AGENT_DIR` env), `pi` bin removed from OUR
  package (only `ramanujan` ships), installer uses a direct launcher shim —
  never `npm link` (which would re-shadow genuine pi under the shared package
  name kept for merge-ability) — plus a guard that removes a stale self-link
  and restores genuine pi from the registry. This Mac repaired live:
  `pi` → genuine 0.85.1 (`~/.pi` untouched), `ramanujan` → 0.4.3
  (`~/.ramanujan`). Verified: runtime `getAgentDir`/`getAuthPath` resolve
  under `~/.ramanujan`; gates green.
- **Setup polish v4 (2026-09-06, uncommitted).** Banner now renders INSIDE
  each setup screen (`header` opt on selector/input, `theme.fg("accent")` —
  same art + color as homepage) instead of scrollback `console.log` (which
  duplicated and lost theming). One banner visible at a time; each screen
  replaces the last. `console.clear()` on "open chat" still guarantees the
  clean home state. All opts optional — pi callers unaffected; verified
  headlessly + gates green (pytest 153, ruff, bridge 20 / config 18 /
  math-tools 33, 50-file bundle).
- **Setup polish v3 (2026-09-06, uncommitted).** Wizard banner removed (boot
  homepage owns the single themed ASCII — no more white duplicate, no color
  mismatch); `console.clear()` on "Yes — open chat" so home lands on the
  normal default state with zero setup residue in scrollback. Nothing else
  changed; gates green (pytest 153, ruff, bridge 20 / config 18 / math-tools
  33, 50-file bundle).
- **Setup fixes (2026-09-06, uncommitted).** (a) Invisible text: wizard now
  queries the real terminal background once (OSC 11, 1.5s) and threads an
  explicit light/dark override through `createStartupTui`/`showStartup*`
  (optional params — pi callers unaffected); ASCII banner printed above every
  step. (b) Lists show **4 rows in a scrolling window** with `(x/y)` counter
  (`ExtensionSelectorComponent.maxVisible`, default = all, pi behavior kept);
  **Done is a separate Tab-reachable row** under the list (`footer` opt;
  `showStartupSelector` resolves its value). (c) API key asked **once**:
  method selector (env vs paste) → single input. (d) Models: **full** live
  list ∪ static catalog (no 50-cap), plus "type slug manually" — nemotron and
  friends can no longer hide behind a fetch gap. (e) Main model wired into pi
  chat too (key → pi `AuthStorage`, model → persisted default), so the footer
  shows `(provider) model` and chat uses it. Verified headlessly: 4 rows,
  scroll window, Tab→Done, defaults unchanged; gates green (pytest 153, ruff,
  bridge 20 / config 18 / math-tools 33, full tsgo build).
- **Phase T1 — Stage tools (bridge-backed).** Register the seven tools in §1.2
  in `math-tools` + `extension.ts`; forbid `uv run ramanujan-engine` in the
  agent prompt (bridge only). Tests: existing bridge/tool test shape.
  *Done when:* transcript contains zero `uv run` / `Uninstalled` lines and zero
  raw `--json` dumps on a Goldbach run.
- **Phase T2 — `web_fetch` tool.** New tool + tests + Literature wiring
  (fetch → cite `source_url` or fall back to `model-memory, unverified`).
  *Done when:* a Literature run cites at least one fetched URL.
- **Phase T3 — Checkpoint cards.** `select/confirm/input` cards per stage +
  question-queue rendering; revise loops back into the same stage; timeout
  defaults resurface at Checkpoint C. *Done when:* each stage ends in a
  picker, never a pasted command.
- **Phase T4 — Router + session artifacts.** System-prompt dispatch
  (chat vs research), `problem_spec.json` shown + passed as file,
  DB/text store for literature (jsonl under session dir, journal stays source
  of truth). Remove encoder from the initial path (keep Tier0 for worktrees).
  *Done when:* Goldbach in chat → spec card → confirm → literature → confirm
  → worktrees, all in-TUI.
- **Phase T5 — Parallel worktrees in TUI.** N subagents (preset or manual
  pick), each own provider/model, progress + orchestration files visible,
  cross-help via shared files, final findings report. Reuse `orchestrator.py`
  via tools; TUI renders progress, not logs.
  *Done when:* 2 subagents run in parallel from one preset pick and produce
  one consolidated report.
- **Phase T6 — Installer. DONE (2026-09-06, uncommitted, Mac-verified).**
  `scripts/install.sh`: node>=22 + npm + python>=3.12 checks → `npm run build`
  → global `ramanujan` bin → engine on PATH (`uv tool` > `pipx` > `pip --user`)
  → verifies both, never touches `~/.config/ramanujan`. NOTE: `npm install -g`
  from a packed tarball 404s on the private unreleased `@ramanujan/*` deps, so
  the installer uses `npm link` until those packages are published — same bins,
  same bundle; release swaps that one step. Verified on this Mac end-to-end:
  `ramanujan --version` → 0.4.3 from `/tmp`, `ramanujan-engine replay` works
  outside the repo. Fresh-install smoke = delete config → `ramanujan` →
  wizard (T0) → chat.
- **Phase T1–T5 — still open** (stage tools, `web_fetch`, checkpoint cards,
  router/artifacts, parallel worktrees in TUI). T1 is next and is the direct
  fix for the `uv run` transcript spam (extension registers zero tools today).

## 3. Non-goals / constraints

- No new journal writers: everything through `journal.py` / bridge.
- No CLI surface for the user (CLI stays as debug/eval surface only).
- No pi web-tool copy (does not exist); `web_fetch` is new code with tests.
- Three-way outcome contracts stay (success / explicit-refusal / system-error)
  on every agent; refusal vs system failure never conflated.
- Keys: env > stored 0600, masked everywhere, never in journal/logs.
