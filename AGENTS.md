# AGENTS.md — Ramanujan v0.4

Living instructions for coding agents on this repo. Keep current.

## Frozen decisions (do not change without BUILDLOG entry)
- Python 3.12+, `uv` managed, `pydantic v2` strict for every persisted structure, `pytest`, `ruff`. Node 22+, npm workspaces under `agent/`.
- Event sourcing: `journal.jsonl` append-only, one JSON object per line, is source of truth. Everything else is derived. Python write path via `ramanujan/journal.py`; TS via `@ramanujan/config` journal helper. Frozen 16-event schema (14 + `panel_position`/`panel_advisory`, v0.4 ADR).
- Every LLM call logged: provider + exact model_id, tokens, cost, latency — assistant, encoder, AND panelists. Every deterministic check logs env (z3, sympy, python).
- Budgets enforced, not advisory. Per-statement and per-run cost/time caps; on breach stop cleanly with partial report.
- Claim-type taxonomy frozen v1: 10 tags (see `ramanujan/taxonomy.py` / `specs/claim_taxonomy.json`). Every claim and verdict carries tags.
- Honest failure first-class: `NOT ENCODABLE` is valid; never silently degrade into weak check.
- Vertical for testing: elementary number theory / additive combinatorics over integers (ints, finite sets of ints, sums, primes, factorials, divisibility).
- Precision over recall. Never report false refutation.
- Key policy (amended v0.2): keys MAY live in `~/.config/ramanujan/config.toml` (0600, atomic write). Precedence env > stored > fail. Keys never in journal/logs/reports/stdout/terminal — masked everywhere.
- TS agent renders, Python engine computes. `claim_refuted` ONLY after the independent verifier agrees. Panel + assistant are advisory voices; refutation power belongs solely to the engine.
- v0.3 browser GUI abandoned and deleted. No GUI code remains.

## Frozen v0.4 decisions (TS agent on pi substrate)
- Agent layer = TS only (TUI, providers, tools, hooks, panel). Python = math engine invoked as a tool (`ramanujan-engine` subprocess); never reimplement math in TS.
- Layout: engine at root (frozen) + `agent/` TS workspace (pi packages copied verbatim + `@ramanujan/{bridge,config,math-tools}`). pi files modified vs intact listed in BUILDLOG A2; MIT headers + `agent/LICENSE.pi-main` preserved.
- Bridge: `ramanujan-engine {encode,check,verify,replay} --json`, contract `agent/docs/bridge.md` (TS codes against doc). Python script owns `ramanujan-engine`; TS bin owns `ramanujan` (npm link dev; single-binary bundling deferred).
- One config (`~/.config/ramanujan/config.toml`), one journal (`journal.jsonl`) shared by both runtimes; TS events must pass Python replay. Chats: pi session storage (NOT journal events).
- Agent loop: pi-native tools (`killcheck_encode`, `killcheck_run`, `panel_review`) + `/card` `/runs` `/verdict` `/panel` commands via the `ramanujanExtension` factory. Confirmation gate is human-only, enforced in tool + `tool_call` hook. Verdict strings only inside tool-result cards.
- Panel: sealed round 1 (parallel, no cross-visibility) → engineVerify funnel → open round 2 (attributed, revision) → deterministic advisory. Panel NEVER writes `claim_refuted`.
- Engine CLI (`ramanujan-engine killcheck/replay/confirm/providers/roles`) stays as debug/eval surface. No new engine CLI beyond the bridge.

## Repo layout (frozen)
```
ramanujan/
  pyproject.toml  AGENTS.md  BUILDLOG.md  REPO_NOTES.md  REPO_NOTES-v0.4.md
  ramanujan/
    __init__.py  journal.py  schemas.py  taxonomy.py  config.py
    providers.py  budget.py  claimcard.py  encoder.py
    killcheck/{numeric.py,smt.py,runner.py,verify.py,report.py}
    cli.py  (console script: ramanujan-engine)
  agent/
    package.json  tsconfig.base.json  LICENSE.pi-main  docs/bridge.md
    packages/{ai,agent,tui,client,server,protocol,telemetry,coding-agent,…} (pi, intact)
    packages/{bridge,config,math-tools} (ours)
  evals/{planted/*.json,SHA256SUMS,mutations.py,run_eval.py,run_search_only.py}
  specs/{claim_taxonomy.json,verifier_specs/encoder.yaml}
  tests/
```

## Conventions
- All Python journal writes through `ramanujan/journal.py`; TS through `@ramanujan/config` journal helper (same envelope). Never touch the file otherwise.
- Pydantic validation raises at write time; invalid events never written. New event types only via schema ADR (append-only, replay stays backward-compatible).
- Keys: env override > stored 0600. Never in files except `~/.config/ramanujan/config.toml` (outside repo). Model IDs are verbatim pins (openai-compatible slugs contain `/`).
- Claim card is the IR: `ramanujan/claimcard.py` interpreter is one path; `ramanujan/killcheck/verify.py` is the independent second path — no shared helpers.
- Write tests before/with each module, especially schemas.
- After every sub-task: update `BUILDLOG.md` and `git commit`.
- Never touch `evals/planted/` (SHA256SUMS pinned). Never weaken gates.
- pi/iteris MIT/Apache headers and LICENSE files preserved verbatim. Never commit `pi-main/`, `iteris-main/`, `images/`, `node_modules/`, `agent/dist/`, `session-*.md`.

## Gotchas
- `sympy` parsing quirks: always use `sympy.parsing.sympy_parser.parse_expr` with explicit transformations; test factorial, `2**n`, `|A|` forms. `is_prime` is not symbolic — Python eval path.
- `signal.alarm` only works on main thread — non-main threads fall back to exact evaluation without timeout (see `ramanujan/claimcard.py`).
- `from x import y` + `patch("x.y")` does not affect already-imported `y` in other modules — patch BOTH `ramanujan.providers.call_llm` and `ramanujan.encoder.call_llm` in tests.
- Our TS packages must NOT import pi source types (drags workspace into tsc: unresolvable imports + rootDir violations, verified) — use minimal structural mirrors; real check happens when pi loads our extension.
- All TS builds use tsgo (`@typescript/native-preview`); pi source needs it (stock tsc rejects its regex flags), ours just follows the same toolchain. Our `dist/` is gitignored — tests resolve workspace deps via built `dist`, so build before testing after clean checkouts.
- Z3 ints vs reals: keep domains typed; do not mix without explicit cast.
- Journal replay must be idempotent; never hand-edit derived views.

## Commands
- `ramanujan` (TS, after `cd agent && npm run build && npm link`) — headline path
- `uv run ramanujan-engine killcheck "<statement>"` / `replay` / `confirm` / `providers` / `roles` — debug/eval
- `uv run ramanujan-engine {encode,check,verify} --json` — machine bridge (see `agent/docs/bridge.md`)
- `uv run pytest` / `uv run ruff check .` / `uv run ruff format .`
- `uv run python evals/run_search_only.py` / `uv run python evals/run_eval.py`
- `npm run build --prefix agent` / `npm run test --prefix agent/packages/{bridge,config,math-tools}`

## Reference repos
- `pi-main/` (MIT) and `iteris-main/` (Apache-2.0) are reference + vendor source (see `REPO_NOTES-v0.4.md`). No runtime dependency on the clones. Never commit them.

