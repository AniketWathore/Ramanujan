# Ramanujan v2 — Build Roadmap

Conversion, not rewrite: keep the discipline (atomic journal, three-way outcomes,
independent re-verification, engine-computes/agent-renders), expand the scope
(one ClaimCard → five-stage pipeline). See Build Brief §§0–7.

Living document: each phase has a **Plan** (fixed at creation) and a **Work Log**
(appended as work completes — date, what was done, verification, BUILDLOG commit).

Disciplines (apply to every phase, §6):
- Single writer to `journal.jsonl` via `ramanujan/journal.py` — claims board folds
  over journal entries, never a second file/writer.
- Three-way outcomes (success / explicit-refusal / system-error) on every new agent.
- Engine computes + journals; TS only renders/orchestrates — all crossings via `bridge/`.
- Kill-check 0.00 false-refutation gate stays strict for Stage 1 kill-check only.

---

## Phase 0 — Audit + family registry

Plan:
- [ ] Read `ramanujan/taxonomy.py` + `specs/claim_taxonomy.json`; answer in writing:
      structure-tags (condition reliability table) vs domain-tags (second axis)? (§2)
      Decision: keep as one set, or add a separate domain tag set.
- [ ] Create `family_registry.json` (manual map `provider/model → family:...`, §4.2).
      Never infer family from provider string (openrouter/gpt-5 == openai/gpt-5).
- [ ] Build preset validator: <2 distinct families → explicit unmissable warning
      ("only budget/stall termination, never panel-verified — proceed anyway?").
      Recommend 3+ families; 2 is the floor. Never hard-block single-key users.
- [ ] Wire validator at preset creation time AND dispatcher setup (§4.2 deadlock guard).

Acceptance: taxonomy answer recorded in writing; 1-family preset warns correctly.

### Work Log — Phase 0
- 2026-09-05 — Taxonomy audit (answer in writing): the 10 frozen tags are
  **structure-tags**, not domain-tags. Evidence: (1) all 10 names describe
  logical/proof shape (inequality form, quantifier form, identity, limit,
  existence-via-compactness, construction, induction, algorithmic, equivalence,
  generalization) — none names a mathematical subject; (2) the encoder prompt
  maps `is_prime(...)` primality claims to `"inequality-estimate"`, i.e. a domain
  concept forced into a structure slot, proving the axes conflate in practice;
  (3) domain already lives elsewhere (`problem_spec.json` `domain:
  ["additive-combinatorics"]`). Decision: keep the 10 tags frozen as the
  structure axis (conditions the Phase 10 reliability table); introduce a
  **separate** domain tag set later (vocabulary seeded from
  `problem_spec.domain` + literature index). `taxonomy.py` untouched.
- 2026-09-05 — Family registry + preset validator: new
  `specs/family_registry.json` (manual ref→family map, seeded with the 5 brief
  §4.2 entries; openrouter/gpt-5 and openai/gpt-5-2025-08-07 share
  `family:openai-gpt5`) and `ramanujan/families.py` (`load_registry`,
  `family_of`, `preset_families`, `validate_preset` → `PresetCheck` with
  non-blocking deadlock warning carrying the verbatim §4.2 sentence; exactly-2
  families passes with a 3+ recommendation note; unknown refs share a
  conservative `family:unknown` bucket so unmapped models never inflate the
  count). Tests `tests/test_families.py` (7 cases: relabel-gaming guard,
  single/one/empty preset warn, two-family note, diverse-5 clean, unknown
  bucket). Verification: `uv run pytest -q` 88 green (81 + 7 new),
  `uv run ruff check .` clean. CLI-at-creation + dispatcher-setup wiring
  deferred to Phases 3/5 (no preset store or dispatcher exists yet).

---

## Phase 1 — Initialiser (trimmed, §4.3)

Plan:
- [ ] Define `problem_spec.json` schema (id, domain, statement_informal,
      statement_formal=null at this stage, variables, objective enum,
      known_special_cases, kill_check_config, open_questions_for_user).
- [ ] Initialiser agent with three-way contract (spec / explicit-refusal / system-error).
- [ ] Numeric-search-only kill-check in bare sandbox at this stage. Record
      `run_smt: true` in config but DO NOT execute SMT — deferred to Stage 3.
- [ ] Checkpoint A: structured spec + numeric kill-check result; confirm/revise loop.
      Generalize `PendingCardStore` confirm/edit/reject into reusable `Checkpoint`
      abstraction (content differs per stage, contract identical).
- [ ] Stop = global always-available action; persisted output survives mid-stage halt.

Acceptance: known-false conjecture rejected by numerics alone within minutes,
`statement_formal: null`, `run_smt: true` recorded-not-executed.

### Work Log — Phase 1
- 2026-09-05 — Built, uncommitted (per instruction). Engine: `ramanujan/problem_spec.py`
  (ProblemSpec/VariableSpec/KillCheckConfig schemas, `statement_formal` always None,
  three-way InitialiseResult spec|not_initialisable|initialiser_error mirroring EncodeResult,
  LLM spec-body builder + deterministic `derive_spec_from_card` keyless fallback,
  `run_numeric_killcheck` over the 4 numeric/set searches + independent verify — `smt`
  never imported on the path, enforced by a test that poisons `sys.modules`);
  `ramanujan/checkpoint.py` (generic CheckpointStore: propose→confirm|revise loop,
  same-id re-presentation, journal `checkpoint_reached`/`checkpoint_resolved`,
  `fold_checkpoints`; stop deliberately absent — global out-of-band action);
  `schemas.py` +3 event types (append-only ADR); `ramanujan-engine initialise --json`
  (spec|not_initialisable|initialiser_error exit 0, error exit 1; encoder role as
  interim stand-in with `role_note` until Phase 3 `main_model`; Checkpoint A proposed).
  TS: `engineInitialise` never-throw bridge call + types, interop test, generic
  `CheckpointStore<T>` in math-tools + 4 tests, `bridge.md` initialise section.
- Acceptance verified keyless: prime conjecture → spec (`statement_formal: null`,
  `run_smt: true`, `smt_executed: false`) + numeric `refuted n=40 double_verified`
  via `bounded_exhaustion` + `cp_001`. Gates: pytest 105 green (88+17), ruff clean,
  bridge 14 + math-tools 31 green, tsgo noEmit clean, search-only EVAL PASSED,
  planted untouched. Deferred: TS extension wiring (`/initialise` tool/command),
  preset-store CLI + `main_model` (Phase 3), session-dir `problem_spec.json` (Phase 5
  layout). Note: with a real key configured, the keyed path works but is at the mercy
  of model quality (slow model maxed 2048 tokens on the spec call in one smoke run).

---

## Phase 2 — Literature agent (§4.4)

Plan:
- [ ] Literature agent (three-way contract) + `literature/papers_index.json` +
      `literature/papers/<id>.md`.
- [ ] Every index entry carries `source_url` OR `"provenance": "model-memory, unverified"` —
      no exceptions; hallucinated recall never indistinguishable from retrieved citation.
- [ ] Checkpoint B: short synthesis (not raw dump); confirm/revise loop.

Acceptance: real run's `papers_index.json` has URL or unverified tag on every entry.

### Work Log — Phase 2
- 2026-09-05 — Built, uncommitted (per instruction). Engine: `ramanujan/literature.py`
  (`PaperEntry` with structural provenance validator — `source_url` present ⇒
  `provenance == "retrieved"`, absent ⇒ `"model-memory, unverified"` — plus
  `PapersIndex` with non-empty `synthesis` and deterministic `lit_NNN` ids,
  three-way `LiteratureResult` index|not_searchable|literature_error mirroring
  encoder/initialiser, empty-index honest path for keyless runs, `_balanced_candidates`
  string-aware extractor + `_parse_first_valid` so reasoning-model chain-of-thought
  before the JSON doesn't break parsing, retry feedback on format errors);
  `schemas.py` +1 event type `literature_entry_added` (now 20 frozen); CLI
  `ramanujan-engine literature --json` (index|not_searchable|literature_error exit 0,
  error exit 1; Checkpoint B via `CheckpointStore`, `--spec-file` context,
  `--out-dir` bundle `literature/papers_index.json` + `papers/<id>.md`, encoder role
  interim with `role_note` until Phase 3 `main_model`).
  TS: `engineLiterature` never-throw bridge call (like initialise) + LiteratureResult
  types, `bridge.md` literature section; two bridge interop tests (keyless empty-index
  with `RAMANUJAN_CONFIG` override + transport-failure) and Python 10 tests
  (including an explicit chain-of-thought → JSON extraction test).
- Acceptance verified: keyless → `papers: []` + `synthesis` with "no LLM key" +
  `cp_001` + `out_dir` bundle (provenance vacuously holds); keyed on real
  sumset prompt ("For finite sets A,B, |A+B| >= |A|+|B|-1.") → 2 entries, both
  `model-memory, unverified` (correctly flagged recalled, not fake "retrieved"),
  synthesis paragraph (not a dump), `papers_index.json` entries all carry URL or
  the explicit tag, journal carries `literature_entry_added` ×2 + `checkpoint_reached`.
  Gates: pytest 115 green (105+10), ruff clean, bridge 16 + math-tools 31 green,
  tsgo noEmit clean, search-only EVAL PASSED, planted untouched. Deferred: TS
  extension wiring (`/literature` tool/command), preset-store CLI + `main_model`
  (Phase 3), session-dir `literature/` (Phase 5 layout).

---

## Phase 3 — Global config generalization (§4.2)

Plan:
- [ ] Extend `ramanujan/config.py` + `providers.py`: `provider_pool`, named `presets`
      (`presets.json`, e.g. diverse-5 / fast-3), distinct `main_model` role
      (runs Initialiser, Literature, Tier-1 lint, Reviewer).
- [ ] Mirror in TS `@ramanujan/config`; keys stay in secrets store (env/OS keychain),
      referenced by name only — never in `global_config.json`/`presets.json`/agent-read files.
- [ ] Session start: saved preset selectable in two taps, no provider re-entry.

Acceptance: preset selectable in two taps with no re-entry of provider details.

### Work Log — Phase 3
- 2026-09-05 — Built, uncommitted (per instruction). Python: `ramanujan/config.py`
  extended with `main_model: RoleSpec | None` (`[roles.main_model]` round-trips
  + `providers remove` clears it); `ramanujan/presets.py` new (`~/.config/ramanujan/presets.json`,
  `RAMANUJAN_PRESETS` override, atomic 0600, JSON name→model-refs; validate via
  `families.validate_preset` on every write, warning with verbatim §4.2 deadlock
  sentence, never blocks — 1-family presets still save); `ramanujan/providers.py`
  `resolve_role("main_model")` added; `ramanujan/cli.py` gains `roles set-main-model`
  + `roles show` now prints `main_model` + `presets {list, show, add, remove} --json`
  (validated, deadlock warning unmissable) + shared helper `_resolve_main_model_with_fallback`
  wiring Initialiser + Literature to `main_model` (encoder fallback with note until
  a provider/key is configured; mock path updated to `main_model`). TS mirror:
  `agent/packages/config/src/{types,toml,config}.ts` handle `main_model`; new
  `families.ts` + `presets.ts` (same non-blocking guard, two-tap flow:
  `presets list --json` + `presets add` without re-entering provider details).
- Acceptance verified: `presets add demo nvidia/main-1 google/gemini-3-pro` →
  `presets list --json` shows `ok:true`; single-family add warns "never
  panel-verified" yet still saves; `initialise --json` now reports
  `role_note: main_model` (or fallback note) and `literature --json` the same;
  no keys ever written to `presets.json`. Gates: pytest 120 green (115+5),
  ruff clean, config 15 + bridge 16 + math-tools 31 green, tsgo clean,
  search-only EVAL PASSED. Deferred: dispatcher preset picker wiring (Phase 5)
  and full `global_config.json` vocabulary (§4.8 layout) — Phase 3 replaces the
  interim `encoder` stand-in, it doesn't yet drive dispatcher orchestration.

---

## Phase 4 — Dispatcher + single worktree (N=1, §4.5)

Plan:
- [ ] Generalize Tier-0 engine (`claimcard.py` + `killcheck/` numeric/smt/runner/report)
      from one-ClaimCard-per-run to per-claim, `claim_id`-addressed, repeatable calls.
- [ ] Dispatcher: per-session preset pick/customize; worktree tool access (Tier-0,
      spec + lit-index read, on-demand Tier-2 panel); all engine calls via `bridge/`.
- [ ] Live Tier 0 (always inline, deterministic) + Tier 1 (inline cheap:
      obligation extraction + usage-site checking vs lit index + claims board).
- [ ] New journal event types in `schemas.py` (frozen-envelope extension, §4.9):
      `problem_spec_created`, `literature_entry_added`, `worktree_spawned`,
      `worktree_status_changed`, `claim_posted` (immutable `claim_id`), …

Acceptance: one worktree posts, self-checks, logs multiple claims per session;
no one-ClaimCard-per-run assumption in path.

### Work Log — Phase 4
- 2026-09-05 — Built, uncommitted (per instruction). `schemas.py` +9 event types
  (append-only ADR → 29 frozen; new payloads `WorktreeSpawnedPayload`,
  `WorktreeStatusChangedPayload`, `ClaimPostedPayload`, `ClaimVerificationRoutedPayload`
  with `verification_path: tier0|tier2-verdict|tier2-advisory-only`); `journal.py`
  validates them; `ramanujan/claims.py` (post/route helpers + `fold_claims` fold-to-latest-by-claim_id),
  `tier1.py` (cheap inline lint: obligation extraction + `lit_NNN` citation check vs papers index),
  `worktree.py` (journal-first `WorktreeStore` wt_001… + fold), `dispatcher.py`
  (`Dispatcher` session with single `JournalWriter`: spawn worktree, per-claim
  `post_and_check_claim` assigning `c_001`…, running Tier0 `killcheck_card`
  + Tier1 lint inline + recording `claim_verification_routed: tier0` — Tier2 is Phase 7).
  No worktree ever appends directly; every write goes through `journal.py`.
  CLI `worktree {spawn, status}` + `claim post` (all via the single-writer convention,
  counter restored from the folded board so repeated CLI invocations share the session
  journal). TS: `engineSpawnWorktree` + `enginePostClaim` + types `WorktreeSpawnResult`/
  `ClaimPostResult`, `bridge.md` worktree/claim sections (29-event frozen set).
- Acceptance verified: one worktree (`wt_001`) posts three claims (`c_001` prime
  refuted n=40, `c_002` true survived, `c_003` trivially false refuted) via
  Python `Dispatcher` and via CLI `worktree spawn` → `claim post` ×2 (same journal,
  no second file; `journal.jsonl` + `worktree_spawned`/`claim_posted`/`claim_verification_routed`/
  `check_executed` present; `replay` clean; folded board returns 3 entries;
  three Tier0 runs share the same session `run_id` — one-ClaimCard-per-run is gone
  from the path. Gates: pytest 126 green (120+6), ruff clean, bridge 17 +
  config 15 + math-tools 31 green, tsgo clean, search-only EVAL PASSED.

---

## Phase 5 — Orchestrator, N>1 (§4.5)

Plan:
- [ ] Orchestrator (monitor process, not LLM): spawn/track
      (`running|stalled|waiting_on_user|stopped_error|panel-verified|completed`),
      progress-report cadence, stall detection, per-worktree budgets via generalized
      `budget.py` (time/step/cost each; breach → `stopped_budget`/`stopped_stalled`,
      logged outcome not error).
- [ ] Claims board: writes via orchestrator through `journal.py` only (no direct
      worktree appends); readers fold to latest status per `claim_id`
      (strengthened/refuted/superseded = new entries, same id).
- [ ] Contradiction flagging across worktrees without NL "arguing".
- [ ] Context compaction per worktree → `worktrees/wt_id/local_journal.jsonl` + summary.
- [ ] Stall detection → `stall_detected` events; file layout per §4.8.

Acceptance: two worktrees post contradictory claims; orchestrator flags it.

### Work Log — Phase 5
- 2026-09-05 — Built, uncommitted (per instruction). Extended `budget.py` with
  `WorktreeBudget` (time/step/cost caps, `stopped_budget`/`stopped_stalled`
  as logged outcomes); `schemas.py` + `StallDetectedPayload` + `stall_detected`
  event (now 30 frozen); new `ramanujan/orchestrator.py` (monitor process, not LLM):
  single `JournalWriter` session, `N` `WorktreeStore` + per-worktree budgets,
  `post_and_check_claim` via `journal.py` (single writer, claim_id from folded
  board), Tier0/Tier1 inline, `record_progress` → `shared/progress_reports/wt_N_####.json`,
  `check_stalls` → `stall_detected` + `stalled` status (threshold, `running` only),
  `compact_worktree` → `worktrees/wt_N/local_journal.jsonl` + `summary.md`,
  `find_contradictions` deterministic syntactic negation (`a > b` vs `a <= b`,
  `>=`↔`<`, `==`↔`!=`, `not (X)` vs `X`) cross-worktree (no NL arguing). Claims board
  still single-file (`journal.jsonl`) with fold-to-latest-by-claim_id. CLI
  `orchestrator {check-contradictions, check-stalls}` (re-hydrates from journal);
  `worktree spawn` now re-hydrates existing spawns so `wt_002` is allocated correctly.
- Acceptance verified: `Orchestrator` spawns `wt_001` + `wt_002`, posts
  `n+1 > n` from `wt_001` and `n+1 <= n` from `wt_002` — both `verification_path: tier0` —
  `find_contradictions()` flags exactly one pair `{c_001,c_002}`; same-worktree
  pair not flagged; `orchestrator check-contradictions --json` over the CLI journal
  also reports `count:1`; per-worktree `budget_steps=1` stops only `wt_001` (`stopped_budget`)
  while `wt_002` stays `running`; stall detection after 0.1s threshold flips `wt_001` to
  `stalled` and journals `stall_detected`; progress + compaction write the
  §4.8 layout files. Gates: pytest 130 green (126+4), ruff clean, bridge 17 +
  config 15 + math-tools 31 green, tsgo clean, search-only EVAL PASSED.

---

## Phase 6 — Micro question queue (§4.5 pattern B)

Plan:
- [ ] Question queue (`shared/questions.jsonl`): nullable `worktree_id`
      (orchestrator-level questions use same pattern, no third pattern),
      non-blocking, `timeout_default` applied + logged on expiry.
- [ ] Stage-level "a worktree hit primary stop — stop rest or keep running?"
      MUST be pattern B with default "let the rest keep running" (never blocking).
- [ ] Checkpoint C summary table (worktree → status → best claim → confidence)
      PLUS every timeout-applied assumption listed explicitly/unmissably.
- [ ] `question_posted`, `question_answered_or_defaulted`,
      `checkpoint_reached`, `checkpoint_resolved` events.

Acceptance: orchestrator-level question renders; unanswered default surfaces
in Checkpoint C summary.

### Work Log — Phase 6
- 2026-09-05 — Built, uncommitted (per instruction). `schemas.py` + `QuestionPostedPayload`
  + `QuestionAnsweredOrDefaultedPayload` (nullable `worktree_id`, `timeout_default`,
  `posted_at`/`timeout_sec`), validated in `journal.py` (now 32 frozen events total;
  30 → 32 counted as two new payloads, the event names were already reserved in Phase 4);
  new `ramanujan/questions.py` (non-blocking `QuestionStore`: `post_question` with
  `worktree_id: str|null` — orchestrator-level uses same pattern, no third pattern —
  `answer_question`, `check_timeouts` applying `timeout_default` and journaling
  `question_answered_or_defaulted: defaulted` + `shared/questions.jsonl` mirror,
  `fold_questions` + `timeout_defaults` for Checkpoint C); extended `checkpoint.py`
  `CheckpointRecord.content` + `CheckpointStore.propose(..., content=)` for C;
  extended `orchestrator.py` to own a `QuestionStore` + `CheckpointStore` (re-hydrated),
  `post_question`/`answer_question`/`check_question_timeouts`, `primary_stop_question`
  (Pattern B, orchestrator `worktree_id=None`, `timeout_default: "let the rest keep
  running"` — the stage never blocks), `checkpoint_c_summary` (worktree table
  `best_claim`/`confidence` + every default surfaced) + `propose_checkpoint_c`
  (prompt carries assumptions unmissably) + `worktrees/.../local_journal` compaction
  unchanged. CLI `question {post, answer, check-timeouts}` + `checkpoint {c-summary, propose-c}`
  (all via single `journal.py` writer, `--worktree-id` optional → orchestrator-level);
  TS `enginePostQuestion`/`engineCheckQuestionTimeouts`/`engineCheckpointCSummary` +
  types `QuestionPosted`/`QuestionResult`/`CheckpointCSummary`, `bridge.md`
  question + checkpoint sections (30s timeouts, 32-event frozen set).
- Acceptance verified: orchestrator-level question `worktree_id=None` renders and
  journals `question_posted`; unanswered with 0.05s timeout → `check_timeouts`
  defaults both `q_001` (orchestrator) + `q_002` (per-worktree) to their
  `timeout_default`s; `checkpoint_c_summary` returns `defaults_count:2` and
  `propose_checkpoint_c` prompt contains `Timeout-assumed` assumptions; CLI
  `question post` (no `--worktree-id`) → `c-summary` shows `wt_001` row +
  defaults after `check-timeouts`; same-worktree answer before timeout not
  defaulted. Gates: pytest 134 green (130+4), ruff clean, bridge 18 +
  config 15 + math-tools 31 green, tsgo clean, search-only EVAL PASSED.
  Note: `worktree_id` is nullable by design — orchestrator questions use the
  SAME Pattern B store, no separate queue.

---

## Phase 7 — Tier-2 panel service (§§2, 4.5)

Plan:
- [ ] Generalize `panel.ts` sealed round-1 → engine-verify funnel → open round-2 →
      deterministic advisory, unchanged mechanic; NEW authority model:
      `panel-verified` ONLY where Tier 0 has no applicable check, and only with
      providers from a different family than the caller (`family_registry.json`).
- [ ] Explicit recorded routing per claim:
      `verification_path: tier0 | tier2-verdict | tier2-advisory-only`
      (`claim_verification_routed` + `panel_verdict_issued` events).
      A claim with an unattempted-but-applicable Tier-0 check NEVER falls through
      to panel-verdict by default.
- [ ] Shared on-demand panel service for all worktrees.

Acceptance: claim with available Tier-0 check can never reach `panel-verified`
via Tier 2 alone — explicit test, not assumption.

### Work Log — Phase 7
- 2026-09-05 — Built, uncommitted (per instruction). `schemas.py` + `PanelVerdictIssuedPayload`
  (`panel_verdict_issued` now allows `tier0|tier2-verdict|tier2-advisory-only`; 32 frozen);
  `panel_service.py` new (`is_tier0_applicable` via `real` domains + `TIER0_SUPPORTED_TYPES`,
  `has_tier0_been_attempted`, `route_for_claim` explicit `verification_path` per §2,
  `request_panel_for_claim` mock shared service with `family_registry` different-family
  exclusion + deadlock guard — single-family relabel `openai/gpt-5` ≡ `openrouter/gpt-5`
  cannot grant `panel-verified`); `orchestrator.py` gains `request_panel()` +
  `tier0_applicable()` (`claim_verification_routed` + `panel_verdict_issued` journaled,
  never `claim_refuted`); CLI `orchestrator request-panel --claim-id --worktree-id --card-file
  (--preset|--model-ref) --journal --json` (re-hydrates). TS: `panel.ts` keeps sealed→reveal
  + engine-verify funnel unchanged; new `isTier0Applicable`/`decideVerificationPath` +
  `PanelResult.verificationPath`, `runPanel` now filters by `callerFamily`, journals
  `claim_verification_routed` + `panel_verdict_issued` explicitly; `config/journal.ts`
  extended to 32-event frozen set (Python `replay` validates). Bridge: `panel` section +
  `engineRequestPanel` + `PanelRequestResult`, 60s timeout, shared-service call convention.
- Acceptance verified (explicit test, not assumption): Tier0-applicable prime claim
  (`inequality-estimate` int) already Tier0-routed → `request_panel` with diverse-3
  returns `tier2-advisory-only` (never `panel-verified`); same claim with Tier0
  *not yet attempted* (manual `claim_posted` bypassing dispatcher) → `tier0`
  (must run Tier0 first); non-Tier0 `convergence-limit` real claim → `tier2-verdict`
  `panel-verified` with cross-family eligible list; single-family relabel preset
  (`openai/gpt-5` + `openrouter/gpt-5` same family) even for non-Tier0 claim →
  `tier2-advisory-only` deadlocked; TS `isTier0Applicable`/`decideVerificationPath`
  unit tests mirror Python and `runPanel` writes `verificationPath: tier2-verdict`
  only for non-Tier0 cross-family; bridge `engineRequestPanel` round-trip prime →
  advisory, real → verdict (19 tests include this). Gates: pytest 139 green (134+5),
  ruff clean, bridge 19 + math-tools 33 + config 15 green, tsgo clean,
  search-only EVAL PASSED, planted untouched, `grep -R claim_refuted journal` never
  from panel.

---

## Phase 8 — Consolidation (§4.6)

Plan:
- [ ] Independent re-execution of winning claim(s) over the session fact set,
      built on `verify.py` "no shared helpers" principle (new mechanism for
      session scope, same design — not a from-scratch invention).
- [ ] Cross-worktree coherence check (compose without contradiction/citation drift);
      resolve orchestrator-flagged contradictions unsettled by panel calls.
- [ ] Toolchain pinning: every formal artifact records exact Lean/Mathlib version +
      model snapshot ID; re-run after upgrade visibly flags mismatch, never silently
      re-checks against the new toolchain.
- [ ] Output labeled fact set (`formal|tier0-checked|panel-verified|plausibility-only|refuted`);
      Checkpoint D confirm/revise; `consolidation_completed` event.

Acceptance: Consolidation re-run after Lean/Mathlib upgrade flags version
mismatch instead of silently re-checking.

### Work Log — Phase 8
- 2026-09-05 — Built, uncommitted (per instruction). `schemas.py` + `ConsolidationCompletedPayload`
  (`consolidation_completed` with `facts_count`/`contradictions_found`/`toolchain_*`/
  `mismatch`/`details`; still 32 frozen — payload added, event name already reserved);
  `journal.py` validates it; new `ramanujan/consolidation.py` (lighter than from-scratch:
  independent re-execution per claim via fresh `killcheck_card` + `verify.py` fresh-parse
  principle applied to session fact set, not one claim; cross-worktree coherence via
  `orchestrator.find_contradictions`; toolchain pinning: formal artifacts in `lean/<claim>.json`
  with `lean_version`/`mathlib_version`/`model_snapshot` compared to current
  `get_toolchain_versions()`/CLI `--lean-version` — mismatch sets `mismatch:true` and
  `mismatch_details`, never silent; labeled fact set `formal|tier0-checked|panel-verified|
  plausibility-only|refuted` + `status`→`confidence` written as `consolidation/facts/<id>.json`
  with pinning fields for formal, plus `consolidation_completed` and Checkpoint D
  `checkpoint_reached` stage `consolidation` whose prompt unmissably notes mismatch/
  contradictions). CLI `consolidate --journal --session-dir --lean-version --mathlib-version
  --model-snapshot --json` (single-writer via `journal.py`); bridge `engineConsolidate` +
  `ConsolidationResult` + `consolidate` doc section (60s timeout, shared call convention).
- Acceptance verified: formal artifact `lean/c_001.json` pin `lean4-v1` → first
  `consolidate` with `lean4-v1` → `mismatch:false`, `f_001.json` written;
  second `consolidate` with `lean4-v2` on same session → `mismatch:true`,
  `mismatch_details` contains both versions, visibly flagged (not silent re-check);
  independent re-execution: two worktrees posting contradictory `n+1> n` vs `n+1<=n`
  + prime refuted → `consolidate` finds ≥1 contradiction and labels facts as
  `refuted` + `tier0-checked`/`plausibility-only`; CLI `--json` shows
  `facts_count`/`contradictions`/`mismatch`; bridge `engineConsolidate` round-trip
  same. Gates: pytest 142 green (139+3), ruff clean, bridge 20 + math-tools 33 +
  config 15 green, tsgo clean, search-only EVAL PASSED, `replay` validates.

---

## Phase 9 — Reviewer + final report (§4.7)

Plan:
- [ ] Reviewer agent (three-way contract, `main_model`): plain-language summary +
      technical appendix (labeled fact set, worktree comparison, failed approaches
      as information, not omitted) → `report_final.md`.
- [ ] Final checkpoint: confirm (conclude) / feedback (re-run stage, redirect
      worktrees, re-panel a claim). Global stop stays available, no special case.

Acceptance: confirmed report produced; feedback routes back into the named stage.

### Work Log — Phase 9
- (empty)

---

## Phase 10 — Reliability table + perturbation audits

Plan:
- [ ] Reliability table conditioned on claim-structure tags (per Phase 0 answer),
      fed by every Tier-2 panel call logged from Phase 7 onward.
- [ ] Perturbation audits over panel verdicts; results feed back into routing
      (which claims may take `tier2-verdict` path).

Acceptance: table updates from live panel calls; audit procedure documented + run.

### Work Log — Phase 10
- (empty)

---

## Phase 11 — Calibration runs

Plan:
- [ ] Three full end-to-end sessions with known outcomes: one true conjecture,
      one false, one genuinely open. Confirm the funnel reaches the right terminal
      state on each (catches integration bugs like family-deadlock that unit tests miss).
- [ ] First real proof the whole pipeline terminates when it should.

Acceptance: all three sessions terminate in the correct terminal state.

### Work Log — Phase 11
- (empty)

---

## Open questions — flag to user, don't assume (§7)

- Meaning of the 10 taxonomy tags (Phase 0) — answered in writing before building on it.
- pi-substrate TUI slash-command extension in place vs new checkpoint/question surface —
  build on existing substrate unless the five-stage flow concretely doesn't fit.
