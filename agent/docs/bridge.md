# Bridge contract — Python engine ↔ TS agent

The TS agent NEVER computes math verdicts. It shells out to
`ramanujan-engine` (Python console script, `ramanujan.cli:main`) and renders
the JSON it returns. This doc is the contract — TS codes against this doc,
not the Python source.

## Binary

`ramanujan-engine` must be reachable — resolved as: explicit `engineBin`
opt (non-default) > `RAMANUJAN_ENGINE_BIN` env > `<cwd>/.venv/bin/ramanujan-engine`
when present (plain repo-checkout TUI launch, no PATH entry needed) > bare
`ramanujan-engine` via PATH. The bridge spawns the binary directly — never
via `uv run` — so a running TUI never triggers installs, syncs, or downloads.
Every command below takes `--json` for machine output: exactly
one JSON object on stdout, exit 0 for verifiable outcomes, exit 1 for
operational errors (`{status:"error", message}`). (Click arg-validation
errors exit 2 with usage text — treat as error.)

Timeouts are enforced on the TS side per call (default 180000ms encode
via `RAMANUJAN_ENCODE_TIMEOUT_MS`, 120s check/initialise/literature/claim, 30s verify/replay/worktree/question/checkpoint).
The encode default is generous because the engine's internal retry loop
(≤3 LLM calls with validation feedback) on a slow model legitimately
exceeds 60s. The check command stays tight — engine checks are fast.

## encode — statement → card

```
ramanujan-engine encode --statement S --journal J --json [--spec P]
```

| status | meaning | exit |
|---|---|---|
| `card` | `{card, run_id, provider, model_id}` — ClaimCard JSON | 0 |
| `not_encodable` | `{reason, run_id, provider, model_id}` — the encoder MODEL itself explicitly refused (its own NOT_ENCODABLE). ONLY this means "outside the DSL" | 0 |
| `encoder_error` | `{reason, run_id, provider, model_id}` — the encoder MODEL failed/timed out, or its card failed validation after retries. NEVER render as "outside the DSL" — render as "encoder model failed, re-run or switch model" | 0 |
| `error` | `{message, run_id}` — spec/key/provider failure | 1 |

Spec resolution: `--spec` yaml, else config `encoder` role
(`~/.config/ramanujan/config.toml`). `provider`/`model_id` echo the pin
that will appear in `llm_call` journal events. `RAMANUJAN_MOCK_ENCODER=1`
uses the planted offline mock (tests only — never acceptance).

Keyless demo: when NO encoder key/role resolves, the bridge encode path
falls back to the keyless offline planted mapping (same hand-written cards
as `evals/run_search_only.py`), journaled with `source: "offline-mapping"`
and `provider: "offline"`. Active ONLY without a key — whenever a spec
resolves (keyed runs, full eval), the mapping is NEVER consulted.

Robustness (v0.4.3): `engineEncode` NEVER throws and NEVER returns empty
output. Transport failures (spawn ENOENT, timeout, empty/non-JSON stdout,
unknown status, engine `error` status) are all returned as `encoder_error`
with the real reason (including the spawn error text) — so the agent always
has something honest to report and never improvises a card.

Journal: `encoding_attempted`, `encoding_accepted`/`encoding_failed`,
`llm_call` (provider + exact model_id) under `run_id`.

## initialise — statement → problem spec + numeric-only kill-check

```
ramanujan-engine initialise --statement S --journal J --json [--spec P] [--small-case-limit N]
```

Stage 1 Initialiser (v2 Phase 1, trimmed scope): structured `ProblemSpec`
(`statement_formal` always null; formalization happens in worktrees) plus a
NUMERIC-search-only kill-check in a bare sandbox. `run_smt: true` is recorded
in the spec but SMT is NEVER executed here — deferred to Stage 3 worktrees.

| status | meaning | exit |
|---|---|---|
| `spec` | `{spec, numeric_killcheck, checkpoint_id, run_id, provider, model_id}` — Checkpoint A proposed | 0 |
| `not_initialisable` | `{reason, run_id, provider, model_id}` — explicit refusal (upstream NOT_ENCODABLE or the model's own NOT_INITIALISABLE). ONLY this means "no specifiable content" | 0 |
| `initialiser_error` | `{reason, run_id, provider, model_id}` — model failure/timeout/validation after retries. NEVER render as "outside scope" | 0 |
| `error` | `{message, run_id}` — spec/key failure, or keyless run on a statement outside the offline mapping | 1 |

`numeric_killcheck`: `{status: refuted|survived, counterexample, double_verified,
methods, checked_total, run_smt: true, smt_executed: false}` — never a verdict
word; `double_verified` true ONLY on independent-verifier agreement.

Model: `--spec` yaml, else config `encoder` role as INTERIM stand-in
(`role_note` in the payload says so until Phase 3 adds `main_model`).
Spec body is LLM-built only on the real keyed path; mock (`RAMANUJAN_MOCK_ENCODER=1`)
and keyless runs derive it deterministically from the card (`RAMANUJAN_MOCK_ENCODER`
uses the planted offline mock, tests only). `engineInitialise` NEVER throws:
transport failures map to `initialiser_error` (120s default timeout).

Journal under `run_id`: `run_started`, encoder `encoding_*`, per-method
`check_executed` (+ `counterexample_found`/`counterexample_reverified` on a
hit — no `claim_refuted`/`claim_survived`; those stay Tier-0 per-claim),
`problem_spec_created`, `checkpoint_reached` (Checkpoint A).

## literature — statement → papers index + synthesis

```
ramanujan-engine literature --statement S --journal J --json [--spec P] [--spec-file F] [--out-dir D]
```

Stage 2 Literature (v2 Phase 2): structured `PapersIndex` (every entry carries
`source_url` OR `provenance: "model-memory, unverified"` — enforced structually
by the `PaperEntry` validator, not just by the prompt) plus a short synthesis
(never a raw dump). Checkpoint B.

| status | meaning | exit |
|---|---|---|
| `index` | `{index: {papers, synthesis}, checkpoint_id, run_id, provider, model_id}` — Checkpoint B proposed | 0 |
| `not_searchable` | `{reason, run_id, provider, model_id}` — explicit refusal (`NOT_SEARCHABLE`). ONLY this means "nothing to survey" | 0 |
| `literature_error` | `{reason, run_id, provider, model_id}` — model failure/timeout/validation after retries. NEVER render as "no prior work" | 0 |
| `error` | `{message, run_id}` — bad args, missing spec-file | 1 |

Keyless/mobile-demo behavior: no key/role → honest empty index (`papers: [], synthesis:
"No literature search performed: no LLM key resolved...") — not an error — still
proposes Checkpoint B with the unconcealed note. LLM survey runs only on the real
keyed path; `RAMANUJAN_MOCK_ENCODER=1` can mock it in tests only. Parsing uses
`_balanced_candidates` so reasoning-model chain-of-thought before the JSON does not
break extraction. `engineLiterature` NEVER throws: transport failures map to
`literature_error` (120s default timeout).

Journal under `run_id`: `run_started`, `llm_call` when keyed, one
`literature_entry_added` per index entry, `checkpoint_reached` (Checkpoint B).
When `--out-dir` is given, the bundle is `literature/papers_index.json` +
`literature/papers/<id>.md` under it; `--spec-file` injects domain/objective
context into the prompt. `index` file strips per-paper `note` (the `.md` holds it).

## worktree — spawn a dispatcher worktree

```
ramanujan-engine worktree spawn --provider P --model-id M --family F --model-ref R --journal J --json
ramanujan-engine worktree status WT_ID STATUS --journal J --json [--reason R]
```

Spawn writes `worktree_spawned` + `worktree_status_changed: running` via the
single `journal.py` writer (no direct appends). Status changes are journaled
the same way. All `wt_NNN` ids are allocated by the engine from the folded
journal (no second file). See `ramanujan/worktree.py`.

## claim — board (fold-to-latest, single writer)

```
ramanujan-engine claim post --worktree-id WT --card-file P --journal J --json [--papers-index IDX]
```

Posts `claim_posted` (immutable `claim_id` allocated as `c_001`… from the
folded board — no caller-supplied id), runs **Tier 0 inline** (the generalized
`killcheck` engine, per-claim `claim_id`-addressed, not one-ClaimCard-per-run)
and **Tier 1 lint** (obligation + `lit_NNN` citation check vs the papers index),
then records `claim_verification_routed: tier0` (Phase 4 all claims are tier0;
Tier 2 panel-verdict lands in Phase 7). Returns the claim's Tier0 verdict +
Tier1 result. Every write goes through `journal.py`; readers fold to the
latest `claim_id` rather than treating the log as flat. On-demand Tier-2 panel
is Phase 7 (shared service, different `verification_path`). All calls go via
this exact convention — no ad-hoc subprocess elsewhere.

## question — micro queue (Pattern B, non-blocking)

```
ramanujan-engine question post --question Q --timeout-default D --journal J --json [--worktree-id WT] [--agent-label L] [--timeout-sec S]
ramanujan-engine question answer --question-id Q --answer A --journal J --json [--answered-by B]
ramanujan-engine question check-timeouts --journal J --json
```

Non-blocking queue (Stage 3 only): one worktree (or the orchestrator itself,
with **no `worktree_id` — nullable**) posts a question; every other worktree
keeps running. `worktree_id` **nullable** — orchestrator-level questions
(`wt_2 has panel-verified… stop rest?` with `timeout_default: "let the rest keep
running"`) use this SAME pattern, not a third one. If unanswered past
`timeout_sec` (default 300s, caller-supplied per question), the system applies
`timeout_default`, journals `question_answered_or_defaulted: defaulted` (and
`shared/questions.jsonl` mirror), and continues. Every default must be surfaced
unmissably in Checkpoint C — never buried in a per-worktree local journal.

## checkpoint — Checkpoint C (computational summary)

```
ramanujan-engine checkpoint c-summary --journal J --json
ramanujan-engine checkpoint propose-c --journal J --json
```

`c-summary` builds the Stage 3 table (`worktree → status → best claim →
confidence`) plus **every timeout-default assumption** from the whole stage
(`timeout_defaults` list) — this is what `propose-c` journals as
`checkpoint_reached` (stage `computational`, prompt carries the assumptions
unmissably). The primary-stop question (`wt_N has panel-verified…`) is itself a
Pattern B micro question with default `let the rest keep running` — the stage
never blocks when the user isn't watching.

## check — card file → verdict

```
ramanujan-engine check --card-file P --journal J --json [--budget-usd X --budget-sec Y]
```

Card file: ClaimCard JSON (as emitted by `encode`). Assignment lists for
set vars are accepted (converted to sets server-side — JSON has no sets).

| status | meaning | exit |
|---|---|---|
| `refuted` | `{run_id, counterexample, double_verified:true, budget, elapsed_sec}` | 0 |
| `survived` | `{run_id, counterexample:null, double_verified:false, budget, elapsed_sec}` | 0 |
| `budget_exceeded` | `{run_id, budget, elapsed_sec}` — honest incomplete | 0 |
| `error` | `{message, run_id}` — bad card file / internal | 1 |

`counterexample` is JSON-safe (sets → sorted lists). `double_verified` is
true ONLY when the independent verifier agreed — the ONLY condition under
which the TS side may render REFUTED. Journal sequence under `run_id`
(identical to the CLI path): `run_started`, `claim_registered`,
`check_executed`×N, `counterexample_found`, `counterexample_reverified`,
`claim_refuted`/`claim_survived`, `run_completed`.

## verify — candidate funnel (panel)

```
ramanujan-engine verify --card-file P --assignment '{"n":41}' --json
```

Pure function — writes NO journal events (candidate probes must not pollute
the audit trail).

| status | meaning | exit |
|---|---|---|
| `counterexample_verified` | `{reason}` — engine confirms refutation | 0 |
| `not_counterexample` | `{reason}` — vacuous / conclusion-true / error | 0 |
| `error` | `{message}` — bad card / bad assignment JSON | 1 |

Goes through `ramanujan/killcheck/verify.py` (fresh parse, no shared
helpers with search). The panel NEVER writes `claim_refuted` — only a
`check` returning `refuted`/`double_verified:true` does.

## replay — journal validation

```
ramanujan-engine replay --journal J --json
```

`{status:"ok", events:[...]}` — validates every line against the frozen
14-event schema (raises on malformed). `{status:"error", message}` + exit 1
on failure. Used by the TS interop gate and run-history list.

## Journal interop

One journal (`journal.jsonl` default), two runtimes. TS-written events
(`llm_call` for assistant/encoder/panelist calls, `ground_truth_recorded`
from ✓/✗ buttons) MUST pass `ramanujan-engine replay --json` validation:
envelope `{ts, run_id, type, payload}`, `type` in the frozen set (30 as of
v2 Phase 5: + `worktree_spawned`/`worktree_status_changed`/`claim_posted`/
`claim_verification_routed`/`stall_detected` + `question_posted`/
`question_answered_or_defaulted`/`checkpoint_reached`/`checkpoint_resolved`/future `panel_verdict_issued`/`consolidation_completed`), `llm_call`
payload carrying `model_id`. Chats/transcripts are NOT journal events.
