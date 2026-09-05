"""Z3 path — ramanujan/killcheck/smt.py"""

from __future__ import annotations

from typing import Any

from ramanujan.schemas import ClaimCard

try:
    import z3  # type: ignore

    HAS_Z3 = True
except Exception:
    HAS_Z3 = False


def _translate_to_z3(expr: str, z3_vars: dict[str, Any]) -> Any:
    """Translate expr string into a Z3 expression using z3_vars as Ints/Reals.

    Supports a restricted subset: arithmetic, comparisons, boolean connectives,
    and a few functions. Returns Z3 BoolRef or ArithRef. Raises on unsupported.
    """
    if not HAS_Z3:
        raise RuntimeError("z3 not available")
    # Provide z3 functions in eval env
    safe: dict[str, Any] = {}
    safe.update(z3_vars)
    # Map factorial/is_prime to uninterpreted helpers that will cause failure for now
    # We intentionally do NOT provide them, so exprs using them will raise.
    # Provide math helpers that have Z3 equivalents:
    # For this slice, handle ^ as ** already, and provide If etc.
    python_expr = expr.replace("^", "**")
    try:
        result = eval(python_expr, {"__builtins__": {}}, safe)  # noqa: S307
    except Exception as e:
        raise ValueError(f"z3 translate failed for {expr!r}: {e}") from e
    return result


def smt_search(card: ClaimCard, *, timeout_ms: int = 5000) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Ask Z3 for a counterexample (hypotheses true, conclusion false).

    Returns (assignment or None, stats dict). Stats includes 'status':
    'sat' (found), 'unsat' (no counterexample in fragment), 'unknown', 'skipped'.
    """
    if not HAS_Z3:
        return None, {"method": "smt", "status": "skipped", "reason": "z3 not installed"}
    if card.set_vars:
        return None, {"method": "smt", "status": "skipped", "reason": "set_card not supported"}
    # Only forall int/real vars
    z3_vars: dict[str, Any] = {}
    for q in card.quantifiers:
        if q.kind != "forall":
            return None, {
                "method": "smt",
                "status": "skipped",
                "reason": "exists quantifier not in SMT fragment",
            }
        if q.domain.type == "int":
            z3_vars[q.var] = z3.Int(q.var)
        elif q.domain.type == "real":
            z3_vars[q.var] = z3.Real(q.var)
        else:
            return None, {
                "method": "smt",
                "status": "skipped",
                "reason": f"domain {q.domain.type} not supported",
            }

    if not z3_vars:
        return None, {"method": "smt", "status": "skipped", "reason": "no forall vars"}

    # Early bail: if conclusion uses factorial/is_prime/sin etc, not in linear fragment
    unsupported_keywords = [
        "factorial",
        "is_prime",
        "isprime",
        "prime",
        "sin",
        "cos",
        "exp",
        "log",
        "sqrt",
    ]
    haystack = card.conclusion.expr + " ".join(card.hypotheses)
    for kw in unsupported_keywords:
        if kw in haystack:
            return None, {"method": "smt", "status": "skipped", "reason": f"unsupported: {kw}"}

    solver = z3.Solver()
    solver.set("timeout", timeout_ms)

    # Add domain bounds as constraints for quantifiers with lo/hi
    for q in card.quantifiers:
        if q.kind != "forall":
            continue
        v = z3_vars[q.var]
        if q.domain.lo is not None:
            try:
                solver.add(v >= int(q.domain.lo))
            except Exception:
                solver.add(v >= q.domain.lo)
        if q.domain.hi is not None:
            try:
                solver.add(v <= int(q.domain.hi))
            except Exception:
                solver.add(v <= q.domain.hi)

    # Add hypotheses
    try:
        for h in card.hypotheses:
            z3_h = _translate_to_z3(h, z3_vars)
            # Ensure BoolRef
            solver.add(z3_h)
    except Exception as e:
        return None, {"method": "smt", "status": "skipped", "reason": f"hyp translate failed: {e}"}

    # Add Not(conclusion)
    try:
        z3_conc = _translate_to_z3(card.conclusion.expr, z3_vars)
        solver.add(z3.Not(z3_conc))  # type: ignore[arg-type]
    except Exception as e:
        return None, {
            "method": "smt",
            "status": "skipped",
            "reason": f"conclusion translate failed: {e}",
        }

    result = solver.check()
    if result == z3.sat:
        model = solver.model()
        assignment: dict[str, Any] = {}
        for var, z3var in z3_vars.items():
            val = model[z3var]
            if val is not None:
                # z3 IntNumRef -> int
                try:
                    if val.sort().kind() == z3.Z3_INT_SORT:
                        assignment[var] = int(val.as_long())
                    elif val.sort().kind() == z3.Z3_REAL_SORT:
                        # Convert rational to float
                        assignment[var] = (
                            float(val.numerator_as_long()) / float(val.denominator_as_long())
                            if hasattr(val, "numerator_as_long")
                            else float(val.as_decimal(10).rstrip("?"))
                        )
                    else:
                        assignment[var] = int(str(val))
                except Exception:
                    assignment[var] = int(str(val))
            else:
                # Model doesn't assign var (unconstrained), pick bound fallback
                q = next(q for q in card.quantifiers if q.var == var)
                lo = q.domain.lo
                assignment[var] = int(lo) if lo is not None else 0
        return assignment, {"method": "smt", "status": "sat", "model": dict(assignment)}
    elif result == z3.unsat:
        return None, {"method": "smt", "status": "unsat"}
    else:
        return None, {"method": "smt", "status": "unknown"}
