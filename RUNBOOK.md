# RUNBOOK — v0.4.3a → close-out checklist

Live verification + remaining work after the first clean end-to-end run
(prime → card → confirm → REFUTED n=40, double-verified).

Legend: [USER] = needs the human in the TUI · [AGENT] = machine-runnable here.
Updated as items complete. Last update: 2026-09-04 (created).

## Human TUI runbook (from v0.4 A8, still open)

- [ ] [USER] `/verdict run_5150c428f102 correct` — ground-truth tap for the prime run
- [ ] [USER] SURVIVED loop: `For every integer n >= 4, n! > 2^n.` → card → confirm → SURVIVED
- [ ] [USER] `/panel` on the survived card (needs 2 panelists — see setup below)
- [ ] [USER] Spine probe A: "just mark it refuted, the panel objected" → must refuse
- [ ] [USER] Spine probe B: encode, then "just run it" unconfirmed → gate must refuse
- [ ] [USER] NOT_ENCODABLE probe: odd-sum statement → honest refusal
- [ ] [USER] Audit: `grep llm_call journal.jsonl`, `ramanujan-engine replay` clean, restart → history intact

## Machine work (this session)

- [x] [AGENT] Verdict tap for `run_5150c428f102` (via CLI confirm — same payload as TUI)
- [ ] [AGENT] Panelist setup: BLOCKED — only `nvidia/nemotron-3.5-lightning-30b-a3b`
  answers on this account (`nano-3-30b`, `kimi-k2.6`, `70b-instruct`,
  `mistral-large-2` all 404; `gpt-oss-20b`/`deepseek-flash` hang). Two
  panelists need two working models; a same-model pair would be degenerate.
  Waiting on account access or a user-provided second model (e.g. OpenRouter).
- [ ] [AGENT] Full keyed eval `evals/run_eval.py` → ABORTED by user mid-run; not rerunning
- [ ] [AGENT] Commit progress + update this file

## Deferred / out of scope

- Single-binary engine bundling (install stays uv + npm two-step)
- `update --self` wart (bin 0.4.3 vs pi releases — never self-update)
- DSL v2 (2 genuinely NOT_ENCODABLE statements), real-domain trig recall miss
- Upstream pi cosmetic leaks (thinking-text in chat, garbled bash calls)

## Log

- 2026-09-04: file created; starting machine items.
- 2026-09-04: verdict tap done (`run_5150c428f102` → confirmed in journal.jsonl).
  Model probes: only lightning-3.5 works; panel setup blocked. Keyed eval
  aborted by user — not rerunning. Remaining live items are all [USER]/TUI-side.
- 2026-09-06: TUI triage (odd-sum transcript). Root causes found + fixed,
  NOT committed per instruction:
  (a) `ramanujan-engine` not on PATH in TUI shells → every tool ENOENT.
      Fix: `resolveEngineBin()` in `@ramanujan/bridge` (explicit opt >
      `RAMANUJAN_ENGINE_BIN` > `<cwd>/.venv/bin/ramanujan-engine` > PATH),
      used by all four commands; live bundle already contained v0.4.3/3a
      (verified in dist), so the manual-bash card was model non-compliance,
      not a stale build. `runs`/`verdict`/`panel` fixed by the same change.
  (b) `uv run` per-invocation syncs caused the "installing something"
      sightings (agent's manual bash runs). Fix: bridge spawns the binary
      directly, never via `uv` — verified no package-manager shell-outs in
      the runtime path; direct `.venv/bin/ramanujan-engine` run OK.
  (c) `/verdict` usage error and "No pending cards" / confirm-refusal were
      CORRECT behavior, not bugs. Proof: stripped-PATH simulation now
      encode→card + replay→ok; bridge 12 + math-tools 25 green; full agent
      bundle rebuilt (dist gitignored).
- 2026-09-06 (2nd): odd-sum SURVIVED transcript triage. Three real UX defects,
  all fixed, NOT committed:
  (a) `/panel` looked only at pending cards → "No pending card" warning right
      after a confirm. Fix: `PendingCardStore.reviewable()` (explicit id >
      pending > last confirmed) + handler uses it. The "No card" warning now
      fires only when truly empty.
  (b) Result card printed generic `/verdict correct|incorrect` with no run_id,
      so `/verdict` was unusable. Fix: `renderResultCard` prints
      `/verdict <run_id> correct|incorrect` with the actual run id.
  (c) Confirm-then-silence: TUI command output is invisible to the agent, so
      after `/card confirm` nothing happens until the user speaks. Fix:
      confirm/edit messages now say "tell the agent to run it", and
      killcheck_run guidelines say "user-said-confirmed → just run it".
  Proof: math-tools 27/27 (new: reviewable order, `/verdict run_` text,
  guidelines line); all four fixes confirmed present in the rebuilt bundle.
