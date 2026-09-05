"""CLI — ramanujan/cli.py

`ramanujan killcheck "<statement>" [--budget-usd 0.50] [--budget-sec 120]`
`ramanujan replay [--journal journal.jsonl]`
`ramanujan confirm <run_id> [correct|incorrect]`
`ramanujan providers ...` / `ramanujan roles ...`
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import click
from rich.console import Console

from ramanujan.budget import BudgetExceeded
from ramanujan.journal import JournalWriter, replay

console = Console()


def _new_run_id() -> str:
    return f"run_{uuid.uuid4().hex[:12]}"


@click.group()
def main() -> None:
    """Ramanujan v0.1 — Math Research Agent kill-check slice."""


@main.command("killcheck")
@click.argument("statement")
@click.option("--budget-usd", default=0.50, type=float, show_default=True, help="Per-run cost cap USD")
@click.option("--budget-sec", default=120.0, type=float, show_default=True, help="Per-run time cap seconds")
@click.option("--journal", default="journal.jsonl", show_default=True, help="Journal path")
def killcheck(statement: str, budget_usd: float, budget_sec: float, journal: str) -> None:
    """Run kill-check sprint on a natural-language conjecture."""
    run_id = _new_run_id()
    jpath = Path(journal)
    writer = JournalWriter(jpath, run_id=run_id)
    start = time.monotonic()
    # run_started
    writer.write("run_started", {"statement": statement, "budget_usd": budget_usd, "budget_sec": budget_sec})
    writer.write("claim_registered", {"statement_informal": statement})

    # Encode
    card = None
    encode_error = None
    # Try offline mapping first for planted statements (so demo works without API key)
    try:
        try:
            from evals.run_search_only import _card as _offline_card  # type: ignore
        except Exception:
            from evals.run_eval import _card as _offline_card  # type: ignore  # legacy fallback

        card = _offline_card(statement)
        if card is not None:
            writer.write("encoding_attempted", {"statement": statement, "attempt": 1, "offline": True})
            writer.write("encoding_accepted", {"card_id": card.card_id, "offline": True})
    except Exception:
        card = None

    if card is None:
        # Try LLM encoder if API key present
        try:
            from ramanujan.encoder import encode_statement
            from ramanujan.providers import load_spec

            spec = load_spec("specs/verifier_specs/encoder.yaml")
            # Check env has key
            import os

            has_key = bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("OPENAI_API_KEY"))
            if not has_key:
                raise RuntimeError("No API key in env (ANTHROPIC_API_KEY or OPENAI_API_KEY) and statement not in offline mapping")
            result = encode_statement(statement, spec, journal=writer, max_retries=3)
            if result.success and result.card is not None:
                card = result.card
            else:
                encode_error = result.error or "encoding failed"
                writer.write("encoding_failed", {"reason": encode_error})
                # NOT ENCODABLE is valid clean outcome
                _report_not_encodable(statement, encode_error, run_id, jpath, start, writer)
                return
        except Exception as e:
            encode_error = str(e)
            with contextlib.suppress(Exception):
                writer.write("encoding_failed", {"reason": encode_error})
            _report_not_encodable(statement, encode_error, run_id, jpath, start, writer)
            return

    # At this point card is ready
    # Run deterministic search
    from ramanujan.killcheck.report import render_report
    from ramanujan.killcheck.runner import killcheck_card

    # Budget is enforced inside runner; we also check elapsed
    try:
        result = killcheck_card(
            card,
            journal=writer,
            budget_usd=budget_usd,
            budget_sec=budget_sec,
            exhaustive_limit=1000,
            random_samples=10000,
        )
    except BudgetExceeded as e:
        # Should not happen as runner handles, but handle
        writer.write("budget_event", {"kind": e.kind, "limit": e.limit, "used": e.used})
        writer.write("run_completed", {"verdict": "BUDGET_EXCEEDED", "elapsed_sec": time.monotonic() - start})
        console.print(f"[yellow]BUDGET EXCEEDED ({e.kind})[/yellow]")
        return

    # Report
    with contextlib.suppress(Exception):
        writer.write(
            "run_completed",
            {
                "verdict": result.verdict,
                "elapsed_sec": time.monotonic() - start,
                "budget_exhausted": result.budget_exhausted,
            },
        )
    report = render_report(card, result, budget_usd=budget_usd, budget_sec=budget_sec)
    console.print(report)
    # Also save report to file
    # Append ground-truth tap hint
    console.print(f"\n[dim]Confirm with: ramanujan confirm {run_id} [correct|incorrect]  (writes ground_truth_recorded)[/dim]")
    # Write report to journal's sibling?
    # For this slice, also write to stdout is enough; save to report file if needed
    # Ensure journal flushed


def _report_not_encodable(statement: str, reason: str, run_id: str, jpath: Path, start: float, writer: JournalWriter) -> None:
    elapsed = time.monotonic() - start
    with contextlib.suppress(Exception):
        writer.write("run_completed", {"verdict": "NOT_ENCODABLE", "reason": reason, "elapsed_sec": elapsed})
    console.print("# Kill-check report — NOT ENCODABLE\n")
    console.print(f"**Statement:** {statement}\n")
    console.print("**Verdict:** NOT ENCODABLE\n")
    console.print(f"**Reason:** {reason}\n")
    console.print(f"**Run ID:** {run_id}")
    console.print(f"**Journal:** {jpath}")
    console.print(f"\n[dim]Confirm with: ramanujan confirm {run_id} [correct|incorrect][/dim]")


@main.command("replay")
@click.option("--journal", default="journal.jsonl", show_default=True, help="Journal path")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output (all events)")
def replay_cmd(journal: str, as_json: bool) -> None:
    """Replay journal.jsonl and print derived state."""
    jpath = Path(journal)
    if as_json:
        try:
            events = replay(jpath)
        except Exception as e:
            _emit_json({"status": "error", "message": str(e)[:500]})
            raise SystemExit(1) from e
        _emit_json({"status": "ok", "events": events})
        return
    events = replay(jpath)
    if not events:
        console.print(f"[dim]No events in {jpath}[/dim]")
        return
    # Counts
    counts: dict[str, int] = {}
    for e in events:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    console.print(f"[bold]Journal replay:[/bold] {jpath} ({len(events)} events)")
    for k, v in sorted(counts.items()):
        console.print(f"  {k}: {v}")
    # Show last 10 events
    console.print("\n[bold]Last 10 events:[/bold]")
    for e in events[-10:]:
        console.print(f"  {e['ts']} {e['run_id']} {e['type']} {json.dumps(e['payload'])[:120]}")
    # Also show run_ids
    run_ids = sorted({e["run_id"] for e in events})
    console.print(f"\n[dim]Run IDs: {', '.join(run_ids[:10])}{' ...' if len(run_ids) > 10 else ''}[/dim]")


@main.command("confirm")
@click.argument("run_id")
@click.argument("resolution", type=click.Choice(["correct", "incorrect"]))
@click.option("--journal", default="journal.jsonl", show_default=True, help="Journal path")
def confirm(run_id: str, resolution: str, journal: str) -> None:
    """Record ground truth for a run (writes ground_truth_recorded event)."""
    jpath = Path(journal)
    writer = JournalWriter(jpath, run_id=run_id)
    target = "f_0001"
    mapped = "confirmed" if resolution == "correct" else "refuted"
    payload: dict[str, Any] = {"target": target, "resolution": mapped, "source": "human"}
    from ramanujan.schemas import GroundTruthPayload

    GroundTruthPayload.model_validate({"target": target, "resolution": mapped, "source": "human"})
    writer.write("ground_truth_recorded", payload)
    console.print(f"[green]Recorded ground truth[/green] for {run_id}: {resolution} -> {mapped}")
    console.print(f"[dim]Journal: {jpath}[/dim]")


# ---------------------------------------------------------------------------
# Providers management
# ---------------------------------------------------------------------------


@main.group("providers")
def providers_group() -> None:
    """Manage LLM providers (keys, models)."""


@providers_group.command("add")
@click.argument("provider_id")
@click.option("--name", required=True, help="Display name")
@click.option("--base-url", required=True, help="OpenAI-compatible base URL, e.g. https://integrate.api.nvidia.com/v1")
@click.option("--api-key-env", default=None, help="Env var for key (env overrides stored)")
@click.option("--family", required=True, help="Family id for panel exclusion")
@click.option("--api-key", default=None, help="Stored key (use prompt if omitted and env not set)")
def providers_add(provider_id: str, name: str, base_url: str, api_key_env: str | None, family: str, api_key: str | None) -> None:
    """Add or update a provider. Prompts for key if needed."""
    from ramanujan.config import ProviderConfig, load_config, save_config

    cfg = load_config()
    cfg.provider_by_id(provider_id)

    # Resolve key: flags-only vs interactive
    stored_key = api_key
    if stored_key is None and api_key_env:
        env_val = os.environ.get(api_key_env)
        if not env_val:
            # Prompt
            stored_key = click.prompt(
                f"Enter API key for provider {provider_id} (stored 0600, env {api_key_env} overrides)",
                hide_input=True,
                default="",
                show_default=False,
            )
            if not stored_key:
                stored_key = None
    elif stored_key is None and not api_key_env:
        # No env var specified, prompt for stored key
        stored_key = click.prompt(
            f"Enter API key for provider {provider_id} (stored 0600)", hide_input=True, default="", show_default=False
        )
        if not stored_key:
            stored_key = None
            click.echo("No key provided — you can set it later via env or re-run add.")

    # If provider exists, update
    new_prov = ProviderConfig(
        id=provider_id,
        name=name,
        base_url=base_url,
        api_key_env=api_key_env,
        api_key=stored_key,
        family=family,
    )
    # Replace or append
    found = False
    for i, p in enumerate(cfg.providers):
        if p.id == provider_id:
            cfg.providers[i] = new_prov
            found = True
            break
    if not found:
        cfg.providers.append(new_prov)
    save_config(cfg)
    # Masked echo
    from ramanujan.config import mask_key

    status = "env" if (api_key_env and os.environ.get(api_key_env)) else ("stored " + mask_key(stored_key) if stored_key else "missing")
    console.print(f"[green]Provider {provider_id} saved[/green] ({status}) -> {base_url}")


@providers_group.command("list")
def providers_list() -> None:
    """List providers (never prints keys)."""
    from ramanujan.config import key_status, load_config, mask_key

    cfg = load_config()
    if not cfg.providers:
        console.print("[dim]No providers configured. Run `ramanujan providers add ...`[/dim]")
        return
    for p in cfg.providers:
        status = key_status(p)
        masked = ""
        if status == "stored" and p.api_key:
            masked = f" {mask_key(p.api_key)}"
        elif status == "env" and p.api_key_env:
            env_val = os.environ.get(p.api_key_env, "")
            masked = f" {mask_key(env_val)} (env {p.api_key_env})"
        console.print(f"[bold]{p.id}[/bold] {p.name} family={p.family} base_url={p.base_url} key={status}{masked}")


@providers_group.command("models")
@click.argument("provider_id")
def providers_models(provider_id: str) -> None:
    """List available models via GET {base_url}/models."""
    from ramanujan.providers import list_models

    try:
        models = list_models(provider_id)
    except Exception as e:
        console.print(f"[red]Failed to list models for {provider_id}: {e}[/red]")
        raise SystemExit(1) from e
    if not models:
        console.print(f"[dim]No models returned for {provider_id}[/dim]")
        return
    for mid in models:
        console.print(mid)


@providers_group.command("test")
@click.argument("provider_id")
def providers_test(provider_id: str) -> None:
    """Test provider with trivial chat completion."""
    from ramanujan.providers import test_provider

    try:
        res = test_provider(provider_id)
    except Exception as e:
        console.print(f"[red]Test failed for {provider_id}: {e}[/red]")
        raise SystemExit(1) from e
    if res.get("ok"):
        console.print(
            f"[green]OK[/green] provider={provider_id} latency={res.get('latency_ms')}ms key={res.get('masked_key')} model={res.get('model')}"
        )
        if res.get("response"):
            console.print(f"  response: {res['response'][:100]}")
    else:
        console.print(
            f"[red]FAIL[/red] provider={provider_id} latency={res.get('latency_ms')}ms key={res.get('masked_key')} error={res.get('error')}"
        )
        raise SystemExit(1)


@providers_group.command("remove")
@click.argument("provider_id")
def providers_remove(provider_id: str) -> None:
    """Remove a provider."""
    from ramanujan.config import load_config, save_config

    cfg = load_config()
    before = len(cfg.providers)
    cfg.providers = [p for p in cfg.providers if p.id != provider_id]
    if len(cfg.providers) == before:
        console.print(f"[yellow]Provider {provider_id} not found[/yellow]")
        raise SystemExit(1)
    # Also remove from roles if used
    if cfg.roles.encoder and cfg.roles.encoder.provider == provider_id:
        cfg.roles.encoder = None
    if cfg.roles.assistant and cfg.roles.assistant.provider == provider_id:
        cfg.roles.assistant = None
    if cfg.roles.main_model and cfg.roles.main_model.provider == provider_id:
        cfg.roles.main_model = None
    if cfg.roles.panel:
        cfg.roles.panel = [r for r in cfg.roles.panel if r.provider != provider_id]
    save_config(cfg)
    console.print(f"[green]Provider {provider_id} removed[/green]")


# ---------------------------------------------------------------------------
# Roles management
# ---------------------------------------------------------------------------


@main.group("roles")
def roles_group() -> None:
    """Manage role assignments (encoder, etc.)."""


@roles_group.command("show")
def roles_show() -> None:
    """Show current role assignments."""
    from ramanujan.config import load_config

    cfg = load_config()
    if cfg.roles.encoder:
        console.print(f"encoder: provider={cfg.roles.encoder.provider} model_id={cfg.roles.encoder.model_id}")
    else:
        console.print("encoder: [dim]not set[/dim] — run `ramanujan roles set-encoder <provider> <model>`")
    if cfg.roles.assistant:
        console.print(f"assistant: provider={cfg.roles.assistant.provider} model_id={cfg.roles.assistant.model_id}")
    else:
        console.print("assistant: [dim]not set (reserved)[/dim]")
    if cfg.roles.main_model:
        console.print(f"main_model: provider={cfg.roles.main_model.provider} model_id={cfg.roles.main_model.model_id}")
    else:
        console.print(
            "main_model: [dim]not set[/dim] — run `ramanujan roles set-main-model <provider> <model>` "
            "(used by Initialiser, Literature, Tier-1, Reviewer)"
        )
    if cfg.roles.panel:
        for i, r in enumerate(cfg.roles.panel):
            console.print(f"panel[{i}]: provider={r.provider} model_id={r.model_id}")
    else:
        console.print("panel: [dim]not set (reserved)[/dim]")


@roles_group.command("set-encoder")
@click.argument("provider_id")
@click.argument("model_id")
def roles_set_encoder(provider_id: str, model_id: str) -> None:
    """Set encoder role to provider/model (model_id is the pin, stored verbatim)."""
    from ramanujan.config import RoleSpec, load_config, save_config

    cfg = load_config()
    prov = cfg.provider_by_id(provider_id)
    if prov is None:
        console.print(f"[red]Provider {provider_id!r} not found. Run `ramanujan providers list`[/red]")
        raise SystemExit(1)
    # Validate pin via providers anti-alias rule
    from ramanujan.providers import ResolvedSpec, _validate_model_pin

    # Build a temporary spec for validation
    tmp = ResolvedSpec(
        provider=prov.id,
        provider_name=prov.name,
        base_url=prov.base_url,
        model_id=model_id,
        family=prov.family,
        role="encoder",
    )
    try:
        _validate_model_pin(tmp)
    except Exception as e:
        console.print(f"[red]Model pin validation failed: {e}[/red]")
        raise SystemExit(1) from e
    cfg.roles.encoder = RoleSpec(provider=provider_id, model_id=model_id)
    save_config(cfg)
    console.print(f"[green]Encoder set[/green] to {provider_id} / {model_id}")


@roles_group.command("set-assistant")
@click.argument("provider_id")
@click.argument("model_id")
def roles_set_assistant(provider_id: str, model_id: str) -> None:
    """Set assistant role (reserved, for future GUI)."""
    from ramanujan.config import RoleSpec, load_config, save_config

    cfg = load_config()
    prov = cfg.provider_by_id(provider_id)
    if prov is None:
        console.print(f"[red]Provider {provider_id!r} not found[/red]")
        raise SystemExit(1)
    from ramanujan.providers import ResolvedSpec, _validate_model_pin

    tmp = ResolvedSpec(
        provider=prov.id,
        provider_name=prov.name,
        base_url=prov.base_url,
        model_id=model_id,
        family=prov.family,
        role="assistant",
    )
    try:
        _validate_model_pin(tmp)
    except Exception as e:
        console.print(f"[red]Model pin validation failed: {e}[/red]")
        raise SystemExit(1) from e
    cfg.roles.assistant = RoleSpec(provider=provider_id, model_id=model_id)
    save_config(cfg)
    console.print(f"[green]Assistant set[/green] to {provider_id} / {model_id}")


@roles_group.command("set-main-model")
@click.argument("provider_id")
@click.argument("model_id")
def roles_set_main_model(provider_id: str, model_id: str) -> None:
    """Set main_model role (Initialiser, Literature, Tier-1, Reviewer)."""
    from ramanujan.config import RoleSpec, load_config, save_config

    cfg = load_config()
    prov = cfg.provider_by_id(provider_id)
    if prov is None:
        console.print(f"[red]Provider {provider_id!r} not found[/red]")
        raise SystemExit(1)
    from ramanujan.providers import ResolvedSpec, _validate_model_pin

    tmp = ResolvedSpec(
        provider=prov.id,
        provider_name=prov.name,
        base_url=prov.base_url,
        model_id=model_id,
        family=prov.family,
        role="main_model",
    )
    try:
        _validate_model_pin(tmp)
    except Exception as e:
        console.print(f"[red]Model pin validation failed: {e}[/red]")
        raise SystemExit(1) from e
    cfg.roles.main_model = RoleSpec(provider=provider_id, model_id=model_id)
    save_config(cfg)
    console.print(f"[green]main_model set[/green] to {provider_id} / {model_id}")


@roles_group.command("set-panel")
@click.argument("provider_id")
@click.argument("model_id")
def roles_set_panel(provider_id: str, model_id: str) -> None:
    """Append a panelist (multi-model panel; cross-provider is the point)."""
    from ramanujan.config import RoleSpec, load_config, save_config

    cfg = load_config()
    prov = cfg.provider_by_id(provider_id)
    if prov is None:
        console.print(f"[red]Provider {provider_id!r} not found[/red]")
        raise SystemExit(1)
    from ramanujan.providers import ResolvedSpec, _validate_model_pin

    tmp = ResolvedSpec(
        provider=prov.id,
        provider_name=prov.name,
        base_url=prov.base_url,
        model_id=model_id,
        family=prov.family,
        role="panelist",
    )
    try:
        _validate_model_pin(tmp)
    except Exception as e:
        console.print(f"[red]Model pin validation failed: {e}[/red]")
        raise SystemExit(1) from e
    cfg.roles.panel = (cfg.roles.panel or []) + [RoleSpec(provider=provider_id, model_id=model_id)]
    save_config(cfg)
    console.print(f"[green]Panelist added[/green] {provider_id} / {model_id} (panel size {len(cfg.roles.panel)})")
    _warn_panel_family(cfg)


@roles_group.command("clear-panel")
def roles_clear_panel() -> None:
    """Remove all panelists."""
    from ramanujan.config import load_config, save_config

    cfg = load_config()
    cfg.roles.panel = []
    save_config(cfg)
    console.print("[green]Panel cleared[/green]")


def _warn_panel_family(cfg: Any) -> None:
    """Warn when all panelists share one family (cross-provider is the point)."""
    panel = cfg.roles.panel or []
    if len(panel) >= 2:
        families = set()
        for r in panel:
            p = cfg.provider_by_id(r.provider)
            families.add(p.family if p else r.provider)
        if len(families) == 1:
            console.print(
                f"[yellow]Warning: all {len(panel)} panelists are family '{next(iter(families))}' — cross-provider panels debate better.[/yellow]"
            )


# ---------------------------------------------------------------------------
# Presets (v2 Phase 3) — validated, never hard-blocks
# ---------------------------------------------------------------------------


@main.group("presets")
def presets_group() -> None:
    """Manage dispatcher presets (validated against family_registry)."""


@presets_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON")
def presets_list(as_json: bool) -> None:
    """List presets: name → models → family check (warn explicitly on deadlock)."""
    from ramanujan.presets import load_presets, validate_all_presets

    presets = load_presets()
    checks = validate_all_presets(presets)
    if as_json:
        out: dict[str, Any] = {}
        for name, models in presets.items():
            chk = checks[name]
            out[name] = {
                "models": models,
                "families": sorted(chk.families),
                "ok": chk.ok,
                "warning": chk.warning,
                "note": chk.note,
            }
        _emit_json({"status": "ok", "presets": out})
        return
    if not presets:
        console.print("[dim]No presets. Run `ramanujan presets add <name> <model>...`[/dim]")
        return
    for name, models in presets.items():
        chk = checks[name]
        fam = ", ".join(sorted(chk.families)) or "none"
        line = f"[bold]{name}[/bold] ({len(models)} models, families: {fam})"
        if not chk.ok and chk.warning:
            line += f" [yellow]⚠ {chk.warning}[/yellow]"
        elif chk.note:
            line += f" [dim]{chk.note}[/dim]"
        console.print(line)
        for m in models:
            console.print(f"  - {m}")


@presets_group.command("show")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True)
def presets_show(name: str, as_json: bool) -> None:
    """Show one preset with its deadlock check."""
    from ramanujan.presets import check_preset, get_preset

    models = get_preset(name)
    if models is None:
        console.print(f"[red]Preset {name!r} not found[/red]")
        raise SystemExit(1)
    chk = check_preset(name, models)
    if as_json:
        _emit_json(
            {
                "status": "ok",
                "name": name,
                "models": models,
                "families": sorted(chk.families),
                "ok": chk.ok,
                "warning": chk.warning,
                "note": chk.note,
            }
        )
        return
    console.print(f"[bold]{name}[/bold] → {', '.join(models)}")
    console.print(f"families: {', '.join(sorted(chk.families)) or 'none'}")
    if chk.warning:
        console.print(f"[yellow]{chk.warning}[/yellow]")
    if chk.note:
        console.print(f"[dim]{chk.note}[/dim]")
    if chk.ok:
        console.print("[green]Preset will reach panel-verified stops.[/green]")
    else:
        console.print("[yellow]Preset can only reach budget/stall termination.[/yellow]")


@presets_group.command("add")
@click.argument("name")
@click.argument("models", nargs=-1, required=True)
def presets_add(name: str, models: tuple[str, ...]) -> None:
    """Add/update a preset (refs like 'anthropic/claude-opus-5'); warns on deadlock, never blocks."""
    from ramanujan.presets import set_preset

    chk = set_preset(name, list(models))
    console.print(f"[green]Preset {name!r} saved[/green] ({len(chk.models)} models, families: {', '.join(sorted(chk.families)) or 'none'})")
    if chk.warning:
        console.print(f"[yellow]⚠ {chk.warning}[/yellow]")
    if chk.note:
        console.print(f"[dim]{chk.note}[/dim]")


@presets_group.command("remove")
@click.argument("name")
def presets_remove(name: str) -> None:
    """Remove a preset."""
    from ramanujan.presets import delete_preset

    if not delete_preset(name):
        console.print(f"[yellow]Preset {name!r} not found[/yellow]")
        raise SystemExit(1)
    console.print(f"[green]Preset {name!r} removed[/green]")


# ---------------------------------------------------------------------------
# Machine bridge (v0.4 A3) — the ONLY new CLI surface.
# JSON contract documented in agent/docs/bridge.md. TS codes against the doc.
# exit 0 for verifiable outcomes (card/not_encodable/refuted/survived/
# budget_exceeded/counterexample_verified/not_counterexample);
# exit 1 for errors (bad args, missing files, internal failure).
# ---------------------------------------------------------------------------


def _emit_json(obj: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(obj))
    sys.stdout.write("\n")
    sys.stdout.flush()


def _mock_encoder_caller():
    """Test-only mock (RAMANUJAN_MOCK_ENCODER=1): planted offline cards."""
    from evals.run_eval import _mock_caller  # type: ignore

    return _mock_caller


def _offline_planted_card(statement: str):
    """Keyless-demo offline mapping: planted statement -> ClaimCard.

    Uses the same hand-written cards as evals/run_search_only.py. Active ONLY
    when no encoder key/role resolves (demo without a key). Full keyed runs
    MUST NEVER consult this — the bridge encode path skips it whenever a
    spec (key) resolves.
    """
    try:
        from evals.run_search_only import _card as _offline_card  # type: ignore
    except Exception:
        return None
    try:
        return _offline_card(statement)
    except Exception:
        return None


def _is_missing_key_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return ("not configured" in msg) or ("no key" in msg) or ("spec resolution" in msg)


def _resolve_main_model_with_fallback(spec: str | None) -> tuple[Any | None, str, Exception | None]:
    """Resolve model for Initialiser/Literature/Reviewer: main_model > encoder fallback.

    Returns (resolved, role_note, spec_error). spec_error is None on success.
    Explicit --spec wins; otherwise try main_model then encoder. Mock fallback
    is handled by callers.
    """
    if spec:
        from ramanujan.providers import load_spec

        try:
            return load_spec(spec), "explicit --spec", None
        except Exception as e:
            return None, "", e
    from ramanujan.providers import resolve_role

    try:
        return resolve_role("main_model"), "main_model", None
    except Exception as e_main:
        try:
            return resolve_role("encoder"), f"encoder (fallback; main_model not ready: {e_main})", None
        except Exception:
            return None, "", e_main


@main.command("encode")
@click.option("--statement", required=True, help="Natural-language conjecture")
@click.option("--journal", default="journal.jsonl", show_default=True)
@click.option("--spec", default=None, help="VerifierSpec yaml path (overrides config role)")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
def encode(statement: str, journal: str, spec: str | None, as_json: bool) -> None:
    """Encode statement → claim card (machine surface for TS bridge)."""
    from ramanujan.journal import JournalWriter

    run_id = f"enc_{uuid.uuid4().hex[:12]}"
    writer = JournalWriter(Path(journal), run_id=run_id)
    # Resolve spec: --spec yaml or config encoder role.
    # Test-only: RAMANUJAN_MOCK_ENCODER=1 with no configured role falls back
    # to a synthetic mock spec (the mock caller ignores it).
    resolved = None
    spec_error: Exception | None = None
    try:
        if spec:
            from ramanujan.providers import load_spec

            resolved = load_spec(spec)
        else:
            from ramanujan.providers import resolve_role

            resolved = resolve_role("encoder")
    except Exception as e:
        spec_error = e
        if os.environ.get("RAMANUJAN_MOCK_ENCODER") == "1" and not spec:
            from ramanujan.providers import ResolvedSpec

            resolved = ResolvedSpec(
                provider="mock",
                provider_name="Mock (offline test)",
                base_url="http://localhost/",
                model_id="mock/offline-prime",
                family="mock",
                role="encoder",
            )
            spec_error = None

    if resolved is None:
        # No key/role: keyless-demo offline mapping ONLY (never on keyed runs).
        if spec_error is not None and _is_missing_key_error(spec_error) and os.environ.get("RAMANUJAN_MOCK_ENCODER") != "1":
            card = _offline_planted_card(statement)
            if card is not None:
                writer.write("encoding_attempted", {"statement": statement, "attempt": 1, "source": "offline-mapping"})
                writer.write("encoding_accepted", {"card_id": card.card_id, "source": "offline-mapping"})
                if as_json:
                    _emit_json(
                        {
                            "status": "card",
                            "card": card.model_dump(),
                            "run_id": run_id,
                            "provider": "offline",
                            "model_id": "offline/planted-mapping",
                        }
                    )
                    return
                console.print_json(data=card.model_dump())
                return
        if as_json:
            _emit_json({"status": "error", "message": f"spec resolution failed: {spec_error}", "run_id": run_id})
            raise SystemExit(1) from spec_error
        console.print(f"[red]Spec resolution failed: {spec_error}[/red]")
        raise SystemExit(1) from spec_error

    provider_id = getattr(resolved, "provider", "unknown")
    model_id = getattr(resolved, "model_id", "unknown")
    caller = _mock_encoder_caller() if os.environ.get("RAMANUJAN_MOCK_ENCODER") == "1" else None

    from ramanujan.encoder import encode_statement

    try:
        result = encode_statement(statement, resolved, journal=writer, caller=caller)  # type: ignore[arg-type]
    except Exception as e:
        if as_json:
            _emit_json({"status": "error", "message": str(e)[:500], "run_id": run_id, "provider": provider_id, "model_id": model_id})
            raise SystemExit(1) from e
        console.print(f"[red]Encode failed: {e}[/red]")
        raise SystemExit(1) from e

    if result.success and result.card is not None:
        if as_json:
            _emit_json(
                {
                    "status": "card",
                    "card": result.card.model_dump(),
                    "run_id": run_id,
                    "provider": provider_id,
                    "model_id": model_id,
                }
            )
            return
        console.print_json(data=result.card.model_dump())
        return
    # Distinguish honest DSL refusal (exit 0, not_encodable) from model
    # failure (exit 0, encoder_error). NEVER report a validation/LLM failure
    # as "statement outside the DSL".
    if result.is_not_encodable:
        if as_json:
            _emit_json(
                {
                    "status": "not_encodable",
                    "reason": result.error,
                    "run_id": run_id,
                    "provider": provider_id,
                    "model_id": model_id,
                }
            )
            return
        console.print(f"[yellow]NOT ENCODABLE: {result.error}[/yellow]")
        return
    if as_json:
        _emit_json(
            {
                "status": "encoder_error",
                "reason": result.error,
                "run_id": run_id,
                "provider": provider_id,
                "model_id": model_id,
            }
        )
        return
    console.print(f"[yellow]ENCODER ERROR (model failed, not a DSL refusal): {result.error}[/yellow]")


@main.command("check")
@click.option("--card-file", required=True, type=click.Path(exists=True, dir_okay=False), help="ClaimCard JSON file")
@click.option("--journal", default="journal.jsonl", show_default=True)
@click.option("--budget-usd", default=0.50, type=float, show_default=True)
@click.option("--budget-sec", default=30.0, type=float, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
def check(card_file: str, journal: str, budget_usd: float, budget_sec: float, as_json: bool) -> None:
    """Run deterministic killcheck on a claim-card file (machine surface)."""
    from ramanujan.journal import JournalWriter

    run_id = _new_run_id()
    writer = JournalWriter(Path(journal), run_id=run_id)
    start = time.monotonic()
    # Load + validate card (same as CLI path)
    try:
        from ramanujan.claimcard import validate_card
        from ramanujan.schemas import ClaimCard

        raw = json.loads(Path(card_file).read_text(encoding="utf-8"))
        card = validate_card(ClaimCard.model_validate(raw))
    except Exception as e:
        if as_json:
            _emit_json({"status": "error", "message": f"card load failed: {e}", "run_id": run_id})
            raise SystemExit(1) from e
        console.print(f"[red]Card load failed: {e}[/red]")
        raise SystemExit(1) from e

    writer.write(
        "run_started", {"statement": card.statement_informal, "source": "engine", "budget_usd": budget_usd, "budget_sec": budget_sec}
    )
    writer.write("claim_registered", {"statement_informal": card.statement_informal, "source": "engine"})

    from ramanujan.killcheck.runner import killcheck_card

    try:
        result = killcheck_card(
            card, journal=writer, budget_usd=budget_usd, budget_sec=budget_sec, exhaustive_limit=1000, random_samples=10000
        )
    except Exception as e:
        if as_json:
            _emit_json({"status": "error", "message": str(e)[:500], "run_id": run_id})
            raise SystemExit(1) from e
        console.print(f"[red]Check failed: {e}[/red]")
        raise SystemExit(1) from e

    elapsed = time.monotonic() - start
    with contextlib.suppress(Exception):
        writer.write(
            "run_completed",
            {"verdict": result.verdict, "elapsed_sec": elapsed, "budget_exhausted": result.budget_exhausted, "source": "engine"},
        )

    ce = result.counterexample
    ce_json = {k: (sorted(v) if isinstance(v, set) else v) for k, v in ce.items()} if ce else None
    double_verified = bool(result.stats.get("verify", {}).get("ok", False)) if result.verdict == "REFUTED" else False
    status = {"REFUTED": "refuted", "SURVIVED": "survived"}.get(result.verdict, "error")
    if result.budget_exhausted:
        status = "budget_exceeded"
    if as_json:
        _emit_json(
            {
                "status": status,
                "run_id": run_id,
                "counterexample": ce_json,
                "double_verified": double_verified,
                "budget": result.stats.get("budget", {}),
                "elapsed_sec": result.stats.get("elapsed_sec", elapsed),
            }
        )
        return
    from ramanujan.killcheck.report import render_report

    console.print(render_report(card, result, budget_usd=budget_usd, budget_sec=budget_sec))


@main.command("verify")
@click.option("--card-file", required=True, type=click.Path(exists=True, dir_okay=False), help="ClaimCard JSON file")
@click.option("--assignment", required=True, help="Witness assignment as JSON, e.g. '{\"n\":41}'")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
def verify(card_file: str, assignment: str, as_json: bool) -> None:
    """Verify a counterexample candidate (panel funnel — pure, no journal writes)."""
    try:
        from ramanujan.schemas import ClaimCard

        raw = json.loads(Path(card_file).read_text(encoding="utf-8"))
        card = ClaimCard.model_validate(raw)
    except Exception as e:
        if as_json:
            _emit_json({"status": "error", "message": f"card load failed: {e}"})
            raise SystemExit(1) from e
        console.print(f"[red]Card load failed: {e}[/red]")
        raise SystemExit(1) from e
    try:
        parsed = json.loads(assignment)
        if not isinstance(parsed, dict):
            raise ValueError("assignment must be a JSON object")
        # JSON cannot carry sets; accept lists for set vars and convert
        wit: dict[str, Any] = {k: (set(v) if isinstance(v, list) and k in (card.set_vars or []) else v) for k, v in parsed.items()}
    except Exception as e:
        if as_json:
            _emit_json({"status": "error", "message": f"assignment parse failed: {e}"})
            raise SystemExit(1) from e
        console.print(f"[red]Assignment parse failed: {e}[/red]")
        raise SystemExit(1) from e

    from ramanujan.killcheck.verify import verify_counterexample

    ok, reason = verify_counterexample(card, wit)
    if as_json:
        _emit_json({"status": "counterexample_verified" if ok else "not_counterexample", "reason": reason})
        return
    console.print(f"[green]COUNTEREXAMPLE VERIFIED[/green] {reason}" if ok else f"[yellow]NOT A COUNTEREXAMPLE[/yellow] {reason}")


@main.command("initialise")
@click.option("--statement", required=True, help="Informal problem statement")
@click.option("--journal", default="journal.jsonl", show_default=True)
@click.option("--spec", default=None, help="VerifierSpec yaml path (overrides config role)")
@click.option("--small-case-limit", default=1000, type=int, show_default=True, help="Numeric exhaustion limit")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
def initialise(statement: str, journal: str, spec: str | None, small_case_limit: int, as_json: bool) -> None:
    """Stage 1 Initialiser: structured spec + numeric-only kill-check (machine surface).

    Three-way outcome (exit 0): spec | not_initialisable (explicit refusal) |
    initialiser_error (model failure). Exit 1 for operational errors only.
    SMT is recorded (run_smt) but never executed here — deferred to Stage 3.
    """
    from ramanujan.journal import JournalWriter

    run_id = f"init_{uuid.uuid4().hex[:12]}"
    writer = JournalWriter(Path(journal), run_id=run_id)
    writer.write("run_started", {"statement": statement, "stage": "initialiser"})

    resolved, role_note, spec_error = _resolve_main_model_with_fallback(spec)
    if resolved is None and os.environ.get("RAMANUJAN_MOCK_ENCODER") == "1" and not spec:
        from ramanujan.providers import ResolvedSpec

        resolved = ResolvedSpec(
            provider="mock",
            provider_name="Mock (offline test)",
            base_url="http://localhost/",
            model_id="mock/offline-prime",
            family="mock",
            role="main_model",
        )
        role_note = "mock (test-only)"
        spec_error = None

    from ramanujan.encoder import EncodeResult, encode_statement

    provider_id = getattr(resolved, "provider", "offline")
    model_id = getattr(resolved, "model_id", "offline/derived")

    def encode_fn(stmt: str) -> EncodeResult:
        if resolved is None:
            card = _offline_planted_card(stmt)
            if card is None:
                raise RuntimeError(
                    f"no key/role ({spec_error}) and statement not in offline mapping — configure a provider or use a planted statement"
                )
            writer.write("encoding_attempted", {"statement": stmt, "attempt": 1, "source": "offline-mapping"})
            writer.write("encoding_accepted", {"card_id": card.card_id, "source": "offline-mapping"})
            return EncodeResult(card=card, error=None, raw="{}", attempts=1)
        caller = _mock_encoder_caller() if os.environ.get("RAMANUJAN_MOCK_ENCODER") == "1" else None
        return encode_statement(stmt, resolved, journal=writer, caller=caller)  # type: ignore[arg-type]

    # Spec-body LLM only on the real keyed path; mock/keyless derive from card.
    use_llm_spec = resolved is not None and os.environ.get("RAMANUJAN_MOCK_ENCODER") != "1"

    from ramanujan.checkpoint import CheckpointStore
    from ramanujan.problem_spec import initialise_statement

    try:
        result = initialise_statement(
            statement,
            encode_fn=encode_fn,
            journal=writer,
            model_spec=resolved if use_llm_spec else None,
            prob_id="prob_001",
            small_case_limit=small_case_limit,
        )
    except Exception as e:
        if as_json:
            _emit_json({"status": "error", "message": str(e)[:500], "run_id": run_id})
            raise SystemExit(1) from e
        console.print(f"[red]Initialise failed: {e}[/red]")
        raise SystemExit(1) from e

    base = {"run_id": run_id, "provider": provider_id, "model_id": model_id, "role_note": role_note}
    if result.success and result.spec is not None and result.numeric is not None:
        store = CheckpointStore(writer)
        cp = store.propose(
            stage="initialiser",
            output_ref=f"run {run_id} problem_spec (inline)",
            prompt="Here's the structured spec and numeric kill-check result. Confirm to proceed, or tell me what to change.",
        )
        if as_json:
            _emit_json(
                {
                    "status": "spec",
                    **base,
                    "spec": result.spec.model_dump(),
                    "numeric_killcheck": result.numeric.model_dump(),
                    "checkpoint_id": cp.checkpoint_id,
                }
            )
            return
        console.print_json(data=result.spec.model_dump())
        console.print(
            f"[bold]Numeric kill-check:[/bold] {result.numeric.status}"
            f"{' at ' + json.dumps(result.numeric.counterexample) if result.numeric.counterexample else ''}"
            f" (methods: {', '.join(result.numeric.methods) or 'none'}; smt_executed={result.numeric.smt_executed})"
        )
        console.print(f"[dim]Checkpoint {cp.checkpoint_id} proposed — confirm or revise.[/dim]")
        return
    if result.is_not_initialisable:
        if as_json:
            _emit_json({"status": "not_initialisable", **base, "reason": result.error})
            return
        console.print(f"[yellow]NOT INITIALISABLE: {result.error}[/yellow]")
        return
    if as_json:
        _emit_json({"status": "initialiser_error", **base, "reason": result.error})
        return
    console.print(f"[yellow]INITIALISER ERROR (model failed, not a refusal): {result.error}[/yellow]")


@main.command("literature")
@click.option("--statement", required=True, help="Informal problem statement")
@click.option("--journal", default="journal.jsonl", show_default=True)
@click.option("--spec", default=None, help="VerifierSpec yaml path (overrides config role)")
@click.option("--spec-file", default=None, help="problem_spec.json path (context for the survey)")
@click.option("--out-dir", default=None, help="Write literature/papers_index.json + papers/<id>.md here")
@click.option("--json", "as_json", is_flag=True, help="Machine-readable JSON output")
def literature(statement: str, journal: str, spec: str | None, spec_file: str | None, out_dir: str | None, as_json: bool) -> None:
    """Stage 2 Literature: survey prior work → papers index + synthesis (machine surface).

    Three-way outcome (exit 0): index | not_searchable (explicit refusal) |
    literature_error (model failure). Exit 1 for operational errors only.
    Every index entry carries a source_url or the explicit unverified tag.
    """
    from ramanujan.journal import JournalWriter, write_json_atomic

    run_id = f"lit_{uuid.uuid4().hex[:12]}"
    writer = JournalWriter(Path(journal), run_id=run_id)
    writer.write("run_started", {"statement": statement, "stage": "literature"})

    # Optional problem-spec context (domain/objective steer the survey).
    spec_context = ""
    if spec_file:
        try:
            raw_spec = json.loads(Path(spec_file).read_text(encoding="utf-8"))
            spec_context = (
                f"domain: {raw_spec.get('domain', [])}; objective: {raw_spec.get('objective', '')}; "
                f"variables: {[v.get('name') for v in raw_spec.get('variables', [])]}; "
                f"open questions: {raw_spec.get('open_questions_for_user', [])}"
            )
        except Exception as e:
            if as_json:
                _emit_json({"status": "error", "message": f"spec-file load failed: {e}", "run_id": run_id})
                raise SystemExit(1) from e
            console.print(f"[red]Spec-file load failed: {e}[/red]")
            raise SystemExit(1) from e

    resolved, role_note, spec_error = _resolve_main_model_with_fallback(spec)
    if resolved is None and os.environ.get("RAMANUJAN_MOCK_ENCODER") == "1" and not spec:
        from ramanujan.providers import ResolvedSpec

        resolved = ResolvedSpec(
            provider="mock",
            provider_name="Mock (offline test)",
            base_url="http://localhost/",
            model_id="mock/offline-lit",
            family="mock",
            role="main_model",
        )
        role_note = "mock (test-only)"
        spec_error = None

    provider_id = getattr(resolved, "provider", "offline")
    model_id = getattr(resolved, "model_id", "offline/empty-index")

    # Keyless/mock runs cannot search: honest empty index (provenance rule
    # holds vacuously). LLM survey only on the real keyed path.
    use_llm = resolved is not None and os.environ.get("RAMANUJAN_MOCK_ENCODER") != "1"
    if resolved is None and spec_error is not None and os.environ.get("RAMANUJAN_MOCK_ENCODER") != "1":
        role_note = f"no key/role ({spec_error}) — empty index"

    from ramanujan.checkpoint import CheckpointStore
    from ramanujan.literature import survey_literature

    try:
        result = survey_literature(
            statement,
            journal=writer,
            model_spec=resolved if use_llm else None,
            spec_context=spec_context,
        )
    except Exception as e:
        if as_json:
            _emit_json({"status": "error", "message": str(e)[:500], "run_id": run_id})
            raise SystemExit(1) from e
        console.print(f"[red]Literature failed: {e}[/red]")
        raise SystemExit(1) from e

    base = {"run_id": run_id, "provider": provider_id, "model_id": model_id, "role_note": role_note}
    if result.success and result.index is not None:
        index = result.index
        out_ref = f"run {run_id} papers_index (inline)"
        out_payload: dict[str, Any] = {}
        if out_dir:
            try:
                root = Path(out_dir) / "literature"
                papers_dir = root / "papers"
                papers_dir.mkdir(parents=True, exist_ok=True)
                write_json_atomic(
                    root / "papers_index.json",
                    {"papers": [p.model_dump(exclude={"note"}) for p in index.papers], "synthesis": index.synthesis},
                )
                for p in index.papers:
                    url_line = p.source_url or "(no URL — model memory)"
                    (papers_dir / f"{p.id}.md").write_text(
                        f"# {p.title}\n\n- id: {p.id}\n- provenance: {p.provenance}\n- source: {url_line}\n\n{p.note}\n",
                        encoding="utf-8",
                    )
                out_ref = str(root / "papers_index.json")
                out_payload = {"out_dir": str(root)}
            except Exception as e:
                if as_json:
                    _emit_json({"status": "error", "message": f"out-dir write failed: {e}", "run_id": run_id})
                    raise SystemExit(1) from e
                console.print(f"[red]Out-dir write failed: {e}[/red]")
                raise SystemExit(1) from e
        store = CheckpointStore(writer)
        cp = store.propose(
            stage="literature",
            output_ref=out_ref,
            prompt="Here's what I found. Confirm to proceed, or tell me what to change.",
        )
        if as_json:
            _emit_json(
                {
                    "status": "index",
                    **base,
                    **out_payload,
                    "index": index.model_dump(),
                    "checkpoint_id": cp.checkpoint_id,
                }
            )
            return
        console.print(f"[bold]Synthesis:[/bold] {index.synthesis}")
        console.print(f"[dim]{len(index.papers)} entries. Checkpoint {cp.checkpoint_id} proposed — confirm or revise.[/dim]")
        return
    if result.is_not_searchable:
        if as_json:
            _emit_json({"status": "not_searchable", **base, "reason": result.error})
            return
        console.print(f"[yellow]NOT SEARCHABLE: {result.error}[/yellow]")
        return
    if as_json:
        _emit_json({"status": "literature_error", **base, "reason": result.error})
        return
    console.print(f"[yellow]LITERATURE ERROR (model failed, not a refusal): {result.error}[/yellow]")


if __name__ == "__main__":
    main()
