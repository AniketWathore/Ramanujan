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
- (empty)

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
- (empty)

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
- (empty)

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
- (empty)

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
- (empty)

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
- (empty)

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
- (empty)

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
- (empty)

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
