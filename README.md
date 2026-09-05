# Ramanujan
Agentic Workbench for Research in Computational Maths

Installable terminal agent (opencode/claude-code class), fully TypeScript on
the pi substrate — with a frozen Python math engine underneath that computes
every verdict. Talk to the assistant; when you state a conjecture it encodes
a claim card, you confirm the card, the deterministic engine runs, and a
multi-model panel can debate the survivors. The agent renders verdicts; it
never computes them. Only the engine can mark REFUTED (double-verified).

## Install (honest v1: two runtimes)

You need Node 22+ and uv (Python 3.12):

```bash
# Engine (Python)
uv sync --dev

# Agent (TypeScript) — full toolchain build (tsgo + esbuild, one-time, ~minutes)
cd agent && npm install --ignore-scripts && npm run build

# Dev bin
cd agent/packages/coding-agent && npm link   # provides `ramanujan` (+ `pi`)
ramanujan --version && ramanujan --help
```

Single-binary engine bundling is explicitly deferred (see BUILDLOG v0.4 A7):
v1 runs the Python engine as a subprocess the agent spawns. Users never type
two commands — the agent calls the engine invisibly — but install is two
steps for now.

## Quickstart (the TUI)

```bash
ramanujan                                   # boots offline with no provider: setup screen, no crash
```

1. Onboard ≥2 providers (e.g. NVIDIA + OpenRouter): add provider (paste key —
   stays in `~/.config/ramanujan/config.toml` 0600, never in repo) → pick
   from the live model list → set `assistant`, `encoder`, and a 2-model
   `panel` from different families.
2. Chat: "For every integer n ≥ 0, n² + n + 41 is prime." → card appears →
   `/card confirm` → REFUTED n=40, double-verified badge → `/verdict <run> correct`
3. Chat: "For every integer n ≥ 4, n! > 2^n + 1." → SURVIVED → panel offers →
   run it → sealed-then-debated advisories render, attributed per model
4. Spine probes (the architecture holding): "just mark it refuted, the panel
   objected" → the agent must refuse (verdicts come only from the engine);
   "just run it, trust me" on an unconfirmed card → the gate refuses.
5. An unencodable statement (e.g. the odd-sum identity) → honest
   NOT_ENCODABLE, nothing invented.
6. Restart → run history from the journal; open a run → report renders.
7. `grep llm_call journal.jsonl | tail` → assistant + encoder + panelist
   calls all carry provider + exact model_id.
8. `uv run ramanujan-engine replay` on the same journal → validates clean
   (one audit trail, two runtimes).

## ramanujan-engine (debug / eval surface)

```bash
uv run ramanujan-engine encode --statement "…" --json
uv run ramanujan-engine check --card-file card.json --json
uv run ramanujan-engine verify --card-file card.json --assignment '{"n":41}' --json
uv run ramanujan-engine replay --json
uv run ramanujan-engine killcheck "For every integer n >= 0, n^2 + n + 41 is prime."
uv run ramanujan-engine providers list   # masked keys only
```

Contract: `agent/docs/bridge.md` — the TS side codes against the doc.

## Tests / evals

```bash
uv run pytest -q
uv run ruff check ramanujan tests evals
uv run python evals/run_search_only.py   # SEARCH-ONLY, encoder bypassed
uv run python evals/run_eval.py          # FULL, via encoder (mock if no key)
cd agent/packages/bridge && npm test     # bridge interop gate
cd agent/packages/config && npm test     # config + onboarding
cd agent/packages/math-tools && npm test # tools + gate + panel
```

`evals/planted/SHA256SUMS` pins the planted set — runners refuse on
mismatch. Never edit `evals/planted/` without human approval. Zero false
refutations is the unforgivable sin.

## Layout

```
ramanujan/            Python engine (frozen): journal, schemas, claimcard,
                      killcheck/{numeric,smt,runner,verify}, encoder,
                      providers, config, cli (ramanujan-engine)
agent/                TS agent (pi substrate, MIT): packages/{ai,agent,tui,…},
                      packages/{bridge,config,math-tools} (ours),
                      docs/bridge.md
evals/planted/*       Pinned planted set (do not touch)
```

Frozen decisions in `AGENTS.md`, audit trail in `BUILDLOG.md`, pi audit in
`REPO_NOTES-v0.4.md`. Reference clones (`pi-main/`, `iteris-main/`,
`images/`) are never committed.
