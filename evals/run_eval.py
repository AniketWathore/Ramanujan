"""Planted eval — FULL MODE — evals/run_eval.py

Full pipeline through ramanujan/encoder.py with real provider.
Config via ~/.config/ramanujan/config.toml or --spec override.
Only this eval may print EVAL PASSED (or EVAL PASSED (MOCK — NOT ACCEPTANCE) when mocked).
"""

from __future__ import annotations

import sys

if "." not in sys.path:
    sys.path.insert(0, ".")

import argparse
import contextlib
import json
import os
import time
from pathlib import Path
from typing import Any

from ramanujan.encoder import encode_statement
from ramanujan.journal import JournalWriter
from ramanujan.killcheck.runner import killcheck_card
from ramanujan.providers import load_spec, resolve_role

# Mock cards for offline/CI — still exercises encoder validation path
_PLANTED_MOCK_CARDS: dict[str, dict[str, Any] | None] = {
    "For every integer n >= 4, n! > 2^n.": {
        "card_id": "c_0001",
        "statement_informal": "For every integer n >= 4, n! > 2^n.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "factorial(n) > 2**n", "sympy_parseable": True},
        "set_vars": [],
    },
    "For every integer n >= 4, n! > 3^n.": {
        "card_id": "c_0001",
        "statement_informal": "For every integer n >= 4, n! > 3^n.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "factorial(n) > 3**n", "sympy_parseable": True},
        "set_vars": [],
    },
    "For all finite nonempty sets A, B of integers, |A+B| >= |A|+|B|-1.": {
        "card_id": "c_0001",
        "statement_informal": "For all finite nonempty sets A, B of integers, |A+B| >= |A|+|B|-1.",
        "claim_type": ["combinatorial-construction"],
        "quantifiers": [
            {"var": "A", "kind": "forall", "domain": {"type": "finite_set_of_ints", "lo": None, "hi": None}},
            {"var": "B", "kind": "forall", "domain": {"type": "finite_set_of_ints", "lo": None, "hi": None}},
        ],
        "hypotheses": [],
        "conclusion": {"expr": "|A+B| >= |A|+|B|-1", "sympy_parseable": True},
        "set_vars": ["A", "B"],
    },
    "For all finite nonempty sets A, B of integers, |A+B| >= |A|+|B|.": {
        "card_id": "c_0001",
        "statement_informal": "For all finite nonempty sets A, B of integers, |A+B| >= |A|+|B|.",
        "claim_type": ["combinatorial-construction"],
        "quantifiers": [
            {"var": "A", "kind": "forall", "domain": {"type": "finite_set_of_ints", "lo": None, "hi": None}},
            {"var": "B", "kind": "forall", "domain": {"type": "finite_set_of_ints", "lo": None, "hi": None}},
        ],
        "hypotheses": [],
        "conclusion": {"expr": "|A+B| >= |A|+|B|", "sympy_parseable": True},
        "set_vars": ["A", "B"],
    },
    "For every integer n >= 0, n^2 + n + 41 is prime.": {
        "card_id": "c_0001",
        "statement_informal": "For every integer n >= 0, n^2 + n + 41 is prime.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "is_prime(n**2 + n + 41)", "sympy_parseable": True},
        "set_vars": [],
    },
    "For all integers n >= 1, the sum 1+3+5+...+(2n-1) equals n^2.": None,
    "There exists an integer m such that for every integer n, m > n.": None,
    "For every real x > 0, sin(x) < x.": {
        "card_id": "c_0001",
        "statement_informal": "For every real x > 0, sin(x) < x.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "x", "kind": "forall", "domain": {"type": "real", "lo": 0, "hi": None}}],
        "hypotheses": ["x > 0"],
        "conclusion": {"expr": "sin(x) < x", "sympy_parseable": True},
        "set_vars": [],
    },
    "For every real x, sin(x) < x.": {
        "card_id": "c_0001",
        "statement_informal": "For every real x, sin(x) < x.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "x", "kind": "forall", "domain": {"type": "real", "lo": -10, "hi": 10}}],
        "hypotheses": [],
        "conclusion": {"expr": "sin(x) < x", "sympy_parseable": True},
        "set_vars": [],
    },
    "For all integers n >= 0, n^2 >= 0.": {
        "card_id": "c_0001",
        "statement_informal": "For all integers n >= 0, n^2 >= 0.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 0, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "n**2 >= 0", "sympy_parseable": True},
        "set_vars": [],
    },
    "For all integers n >= 1, n^2 >= n + 1.": {
        "card_id": "c_0001",
        "statement_informal": "For all integers n >= 1, n^2 >= n + 1.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 1, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "n**2 >= n + 1", "sympy_parseable": True},
        "set_vars": [],
    },
    "For all integers n >= 1, 1+3+5+...+(2n-1) equals n^2 + 1.": {
        "card_id": "c_0001",
        "statement_informal": "For all integers n >= 1, 1+3+5+...+(2n-1) equals n^2 + 1.",
        "claim_type": ["algebraic-identity"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 1, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "n**2 == n**2 + 1", "sympy_parseable": True},
        "set_vars": [],
    },
    "For every integer n >= 3, n! > 2^n.": {
        "card_id": "c_0001",
        "statement_informal": "For every integer n >= 3, n! > 2^n.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 3, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "factorial(n) > 2**n", "sympy_parseable": True},
        "set_vars": [],
    },
    "For every integer n >= 4, n! > 2^n + 1.": {
        "card_id": "c_0001",
        "statement_informal": "For every integer n >= 4, n! > 2^n + 1.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "factorial(n) > 2**n + 1", "sympy_parseable": True},
        "set_vars": [],
    },
    "For every integer n >= 1, n! > 2^n.": {
        "card_id": "c_0001",
        "statement_informal": "For every integer n >= 1, n! > 2^n.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 1, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "factorial(n) > 2**n", "sympy_parseable": True},
        "set_vars": [],
    },
    "For every integer n >= 4, n! > 4^n.": {
        "card_id": "c_0001",
        "statement_informal": "For every integer n >= 4, n! > 4^n.",
        "claim_type": ["inequality-estimate"],
        "quantifiers": [{"var": "n", "kind": "forall", "domain": {"type": "int", "lo": 4, "hi": None}}],
        "hypotheses": [],
        "conclusion": {"expr": "factorial(n) > 4**n", "sympy_parseable": True},
        "set_vars": [],
    },
}


def _mock_caller(spec, messages):  # type: ignore
    text = ""
    for m in messages:
        if m["role"] == "user" and "Statement to encode" in m["content"]:
            text = m["content"]
            break
    for k, v in _PLANTED_MOCK_CARDS.items():
        if k in text:
            if v is None:
                return {
                    "text": json.dumps({"error": "NOT_ENCODABLE", "reason": "v1 DSL cannot express open-form sum or mixed ∃∀"}),
                    "input_tokens": 50,
                    "output_tokens": 20,
                    "cost": 0.0005,
                }
            return {"text": json.dumps(v), "input_tokens": 100, "output_tokens": 80, "cost": 0.001}
    return {
        "text": json.dumps({"error": "NOT_ENCODABLE", "reason": "unknown statement in mock"}),
        "input_tokens": 50,
        "output_tokens": 20,
        "cost": 0.0005,
    }


def _is_keyed(spec: Any | None, use_mock: bool) -> bool:
    if use_mock:
        return False
    # Check if any provider has resolvable key
    try:
        from ramanujan.config import load_config, resolve_provider_key

        cfg = load_config()
        for prov in cfg.providers:
            if resolve_provider_key(prov):
                return True
    except Exception:
        pass
    # Also check spec if provided via --spec and has key
    if spec is not None:
        # For VerifierSpec, check env
        provider = getattr(spec, "provider", "")
        if provider == "anthropic" and os.environ.get("ANTHROPIC_API_KEY"):
            return True
        if provider in ("openai",) and os.environ.get("OPENAI_API_KEY"):
            return True
        # For ResolvedSpec, check resolved key
        try:
            from ramanujan.config import load_config, resolve_provider_key

            cfg = load_config()
            prov = cfg.provider_by_id(getattr(spec, "provider", ""))
            if prov and resolve_provider_key(prov):
                return True
        except Exception:
            pass
    return bool(
        os.environ.get("ANTHROPIC_API_KEY")
        or os.environ.get("OPENAI_API_KEY")
        or os.environ.get("NVIDIA_API_KEY")
        or os.environ.get("OPENROUTER_API_KEY")
    )


def run_one(item: dict[str, Any], journal: JournalWriter | None = None, spec: Any | None = None, use_mock: bool = False) -> dict[str, Any]:
    statement = item["statement"]
    expected = item["expected"]
    note = item.get("note", "")
    start = time.monotonic()
    # Resolve spec if not provided
    if spec is None:
        # Try resolve_role from config, fallback to yaml
        try:
            spec = resolve_role("encoder")
        except Exception:
            try:
                spec = load_spec("specs/verifier_specs/encoder.yaml")
            except Exception as e:
                elapsed = time.monotonic() - start
                return {
                    "statement": statement,
                    "expected": expected,
                    "verdict": "ENCODER_ERROR",
                    "card": None,
                    "note": note,
                    "elapsed_sec": elapsed,
                    "cost": 0.0,
                    "error": f"spec load failed: {e}",
                    "provider": "unknown",
                    "model_id": "unknown",
                }
    provider_id = getattr(spec, "provider", "unknown")
    model_id = getattr(spec, "model_id", "unknown")
    family = getattr(spec, "family", "")
    caller = _mock_caller if use_mock else None
    # Encode
    try:
        enc = encode_statement(statement, spec, journal=journal, caller=caller)  # type: ignore[arg-type]
    except Exception as e:
        elapsed = time.monotonic() - start
        return {
            "statement": statement,
            "expected": expected,
            "verdict": "ENCODER_ERROR",
            "card": None,
            "note": note,
            "elapsed_sec": elapsed,
            "cost": 0.0,
            "error": str(e)[:500],
            "provider": provider_id,
            "model_id": model_id,
            "family": family,
        }
    if not enc.success:
        elapsed = time.monotonic() - start
        is_not_encodable = enc.is_not_encodable
        verdict = "NOT_ENCODABLE" if is_not_encodable else "ENCODER_ERROR"
        return {
            "statement": statement,
            "expected": expected,
            "verdict": verdict,
            "card": None,
            "note": note,
            "elapsed_sec": elapsed,
            "cost": 0.0,
            "error": enc.error,
            "raw": enc.raw,
            "provider": provider_id,
            "model_id": model_id,
            "family": family,
        }
    card = enc.card
    assert card is not None
    result = killcheck_card(card, journal=journal, budget_usd=0.50, budget_sec=30, exhaustive_limit=1000, random_samples=10000)
    elapsed = time.monotonic() - start
    verdict = result.verdict
    cost = float(result.stats.get("budget", {}).get("spent_usd", 0.0) or 0.0)
    return {
        "statement": statement,
        "expected": expected,
        "verdict": verdict,
        "counterexample": result.counterexample,
        "stats": result.stats,
        "note": note,
        "elapsed_sec": elapsed,
        "cost": cost,
        "budget_exhausted": result.budget_exhausted,
        "card_id": card.card_id,
        "provider": provider_id,
        "model_id": model_id,
        "family": family,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Full eval via encoder")
    parser.add_argument("--spec", type=str, default=None, help="Path to VerifierSpec yaml (overrides config)")
    args = parser.parse_args()

    # Checksum verification first
    planted_dir = Path("evals/planted")
    sums_file = planted_dir / "SHA256SUMS"
    if sums_file.exists():
        print("Verifying SHA256SUMS...")
        import hashlib

        ok = True
        for line in sums_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            expected_hash, fname = parts[0], parts[1]
            fname = fname.lstrip("*")
            fpath = planted_dir / fname
            if not fpath.exists():
                fpath = Path(fname)
                if not fpath.exists():
                    fpath = planted_dir / Path(fname).name
            if not fpath.exists():
                print(f"  MISSING {fname}")
                ok = False
                continue
            h = hashlib.sha256(fpath.read_bytes()).hexdigest()
            if h != expected_hash:
                print(f"  MISMATCH {fname}: expected {expected_hash[:8]} got {h[:8]}")
                ok = False
            else:
                print(f"  OK {fname}")
        if not ok:
            print("SHA256SUMS verification FAILED — refusing to run. Regeneration requires human approval.")
            sys.exit(1)
        print("SHA256SUMS OK")
    else:
        print("WARNING: no SHA256SUMS file — run `sha256sum evals/planted/*.json > evals/planted/SHA256SUMS` to create")

    files = sorted(planted_dir.glob("*.json"))
    files = [p for p in files if p.name != "SHA256SUMS"]
    if not files:
        print("No planted files found.")
        return

    # Resolve spec: --spec overrides, else config role
    spec = None
    spec_source = "config"
    if args.spec:
        try:
            spec = load_spec(args.spec)
            spec_source = f"spec:{args.spec}"
        except Exception as e:
            print(f"Failed to load spec {args.spec}: {e}")
            sys.exit(1)
    else:
        try:
            spec = resolve_role("encoder")
            spec_source = "config:encoder"
        except Exception as e:
            # Fallback to yaml for backward compat
            try:
                spec = load_spec("specs/verifier_specs/encoder.yaml")
                spec_source = "spec:encoder.yaml (fallback)"
            except Exception as e2:
                print(f"Failed to resolve encoder role and fallback yaml: {e} / {e2}")
                sys.exit(1)

    # Determine keyed vs mock
    has_key = False
    try:
        from ramanujan.config import load_config, resolve_provider_key

        cfg = load_config()
        for prov in cfg.providers:
            if resolve_provider_key(prov):
                has_key = True
                break
    except Exception:
        pass
    if not has_key:
        has_key = bool(
            os.environ.get("ANTHROPIC_API_KEY")
            or os.environ.get("OPENAI_API_KEY")
            or os.environ.get("NVIDIA_API_KEY")
            or os.environ.get("OPENROUTER_API_KEY")
        )
    # Also check spec's provider key
    if not has_key and spec is not None:
        try:
            from ramanujan.config import load_config, resolve_provider_key

            cfg = load_config()
            prov = cfg.provider_by_id(getattr(spec, "provider", ""))
            if prov and resolve_provider_key(prov):
                has_key = True
        except Exception:
            pass

    use_mock = False
    if not has_key or os.environ.get("RAMANUJAN_MOCK_ENCODER") == "1":
        use_mock = True
        print("FULL MODE — using MOCK encoder (no API key). Still exercises encoder validation path. Set API key for real LLM.")
        print("NOTE: Mock mode — report will say EVAL PASSED (MOCK — NOT ACCEPTANCE)")
    else:
        print(
            f"FULL MODE — using REAL encoder via {spec_source} provider={getattr(spec, 'provider', '?')} model={getattr(spec, 'model_id', '?')}"
        )

    journal = JournalWriter(Path("journal.jsonl"), run_id=f"eval_full_{int(time.time())}")
    journal.write(
        "run_started",
        {
            "statement": "full eval",
            "source": "eval",
            "mode": "full",
            "provider": getattr(spec, "provider", ""),
            "model_id": getattr(spec, "model_id", ""),
            "spec_source": spec_source,
        },
    )

    results: list[dict[str, Any]] = []
    for p in files:
        item = json.loads(p.read_text(encoding="utf-8"))
        res = run_one(item, journal=journal, spec=spec, use_mock=use_mock)
        with contextlib.suppress(Exception):
            journal.write(
                "check_executed",
                {
                    "source": "eval",
                    "file": p.name,
                    "verdict": res["verdict"],
                    "expected": res["expected"],
                    "provider": res.get("provider", ""),
                    "model_id": res.get("model_id", ""),
                },
            )
        results.append(res)
        ce = res.get("counterexample")
        ce_str = str({k: (sorted(v) if isinstance(v, set) else v) for k, v in ce.items()}) if ce else "-"
        err = f" error={res.get('error', '')[:60]}" if res.get("error") else ""
        print(
            f"{p.name}: expected={res['expected']} verdict={res['verdict']} ce={ce_str} time={res['elapsed_sec']:.3f}s cost=${res['cost']:.4f} provider={res.get('provider', '')} model={res.get('model_id', '')}{err}"
        )

    total = len(results)
    true_items = [r for r in results if r["expected"] == "true"]
    false_items = [r for r in results if r["expected"] == "false"]
    not_encodable = sum(1 for r in results if r["verdict"] == "NOT_ENCODABLE")
    encoder_error = sum(1 for r in results if r["verdict"] == "ENCODER_ERROR")
    false_refuted = sum(1 for r in results if r["expected"] == "true" and r["verdict"] == "REFUTED")
    true_refuted = sum(1 for r in results if r["expected"] == "false" and r["verdict"] == "REFUTED")
    false_refutation_rate = false_refuted / len(true_items) if true_items else 0.0
    true_recall = true_refuted / len(false_items) if false_items else 0.0
    not_encodable_rate = not_encodable / total if total else 0.0
    encoder_error_rate = encoder_error / total if total else 0.0
    mean_time = sum(r["elapsed_sec"] for r in results) / total if total else 0.0
    mean_cost = sum(r["cost"] for r in results) / total if total else 0.0

    print("\n=== FULL EVAL SUMMARY ===")
    print(f"total={total} true={len(true_items)} false={len(false_items)}")
    print(f"false-refutation rate (MUST be 0.00): {false_refutation_rate:.3f} ({false_refuted}/{len(true_items)})")
    print(f"true-refutation recall (target >=4/6): {true_refuted}/{len(false_items)} = {true_recall:.3f}")
    print(f"not-encodable rate: {not_encodable_rate:.3f} ({not_encodable}/{total})")
    print(f"encoder-error rate: {encoder_error_rate:.3f} ({encoder_error}/{total})")
    print(f"mean time: {mean_time:.3f}s mean cost: ${mean_cost:.4f}")
    print(f"provider: {getattr(spec, 'provider', '')} model: {getattr(spec, 'model_id', '')} source: {spec_source}")
    exp_not_enc = [
        r
        for r in results
        if r["statement"]
        in (
            "There exists an integer m such that for every integer n, m > n.",
            "For all integers n >= 1, the sum 1+3+5+...+(2n-1) equals n^2.",
        )
    ]
    for r in exp_not_enc:
        if r["verdict"] != "NOT_ENCODABLE":
            print(f"WARNING: expected NOT_ENCODABLE for {r['statement'][:30]} got {r['verdict']}")

    ok = True
    if false_refutation_rate != 0.0:
        print("FAIL: false-refutation rate must be 0.00")
        ok = False
    if encoder_error > 0:
        print(f"FAIL: encoder-error rate must be 0.00 — {encoder_error} items had provider/API failure")
        ok = False
    if true_refuted < 4:
        print(f"WARN: true recall {true_refuted} < 4 (target)")
        if true_refuted < 4:
            ok = False
    if use_mock:
        if ok:
            print("EVAL PASSED (MOCK — NOT ACCEPTANCE)")
        else:
            print("EVAL FAILED (MOCK — NOT ACCEPTANCE)")
    else:
        if ok:
            print("EVAL PASSED")
        else:
            print("EVAL FAILED")

    def _serializable(o: Any) -> Any:
        if isinstance(o, set):
            return sorted(o)
        if isinstance(o, dict):
            return {k: _serializable(v) for k, v in o.items()}
        if isinstance(o, list):
            return [_serializable(x) for x in o]
        return o

    serial_results = [_serializable(r) for r in results]
    out = Path("evals/report.json")
    out.write_text(
        json.dumps(
            {
                "results": serial_results,
                "summary": {
                    "false_refutation_rate": false_refutation_rate,
                    "true_refuted": true_refuted,
                    "total_false": len(false_items),
                    "not_encodable": not_encodable,
                    "encoder_error": encoder_error,
                    "mean_time": mean_time,
                    "mean_cost": mean_cost,
                    "provider": getattr(spec, "provider", ""),
                    "model_id": getattr(spec, "model_id", ""),
                    "spec_source": spec_source,
                    "is_mock": use_mock,
                },
            },
            indent=2,
        )
    )
    print(f"Report written to {out}")
    with contextlib.suppress(Exception):
        journal.write(
            "run_completed",
            {
                "verdict": "EVAL PASSED" if ok else "EVAL FAILED",
                "source": "eval",
                "mode": "full",
                "provider": getattr(spec, "provider", ""),
                "model_id": getattr(spec, "model_id", ""),
                "is_mock": use_mock,
            },
        )
    if encoder_error > 0:
        sys.exit(1)
    if not ok:
        sys.exit(1)


if __name__ == "__main__":
    main()
