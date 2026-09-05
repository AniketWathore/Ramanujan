"""Independent re-verification — ramanujan/killcheck/verify.py

CRITICAL: witness assignment is re-evaluated by a separate code path
(fresh sympy parse, direct evaluation, no shared helpers with search).
Both must agree before claim_refuted.
This module does NOT import from ramanujan.claimcard's evaluation helpers.
"""

from __future__ import annotations

import math
import re
from typing import Any

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from ramanujan.schemas import ClaimCard

_TRANSFORMATIONS = standard_transformations + (convert_xor, implicit_multiplication_application)
_IsPrimeSym = sympy.Function("is_prime")

_SYMPY_LOCALS_VERIFY: dict[str, Any] = {
    "factorial": sympy.factorial,
    "is_prime": _IsPrimeSym,
    "isprime": _IsPrimeSym,
    "prime": sympy.Function("prime"),
    "Abs": sympy.Abs,
    "sqrt": sympy.sqrt,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "exp": sympy.exp,
    "log": sympy.log,
}


def _parse_sympy_verify(expr: str) -> sympy.Basic:
    try:
        return parse_expr(expr, local_dict=_SYMPY_LOCALS_VERIFY, transformations=_TRANSFORMATIONS)
    except Exception as e:
        raise ValueError(f"verify sympy parse failed for {expr!r}: {e}") from e


def _translate_set_verify(expr: str, set_vars: list[str]) -> str:
    out = expr
    for _ in range(5):
        nxt = re.sub(r"\|\s*([^|]+?)\s*\|", r"card(\1)", out)
        if nxt == out:
            break
        out = nxt
    if set_vars:
        for a in set_vars:
            for b in set_vars:
                pat = re.compile(rf"\b{re.escape(a)}\b\s*\+\s*\b{re.escape(b)}\b")
                out = pat.sub(f"sumset({a},{b})", out)
    out = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+subset\s+([A-Za-z][A-Za-z0-9_]*)\b", r"subset(\1,\2)", out)
    return out


def _sumset(a: set[int], b: set[int]) -> set[int]:
    return {x + y for x in a for y in b}


def _is_prime_verify(n: int) -> bool:
    if not isinstance(n, int):
        try:
            n = int(n)
        except Exception:
            return False
    try:
        import sympy as _sym

        return bool(_sym.isprime(n))
    except Exception:
        pass
    if n < 2:
        return False
    if n % 2 == 0:
        return n == 2
    r = int(math.isqrt(n))
    f = 3
    while f <= r:
        if n % f == 0:
            return False
        f += 2
    return True


def _eval_numeric_verify(expr: str, assignment: dict[str, Any]) -> Any:
    # is_prime -> direct python eval
    if "is_prime" in expr or "isprime" in expr or "prime(" in expr:
        python_expr = expr.replace("^", "**")
        safe: dict[str, Any] = {
            "factorial": math.factorial,
            "is_prime": _is_prime_verify,
            "isprime": _is_prime_verify,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "exp": math.exp,
            "log": math.log,
            "Abs": abs,
            "abs": abs,
        }
        safe.update(assignment)
        return eval(python_expr, {"__builtins__": {}}, safe)  # noqa: S307
    try:
        parsed = _parse_sympy_verify(expr)
        subs = {sympy.Symbol(k): v for k, v in assignment.items()}
        result = parsed.subs(subs)
        if result == sympy.true or result == sympy.S.true:
            return True
        if result == sympy.false or result == sympy.S.false:
            return False
        if isinstance(result, (bool, sympy.logic.boolalg.BooleanFunction)):
            return bool(result)
        if result in (True, False):
            return bool(result)
        if isinstance(result, sympy.Basic):
            if result.free_symbols:
                raise ValueError("free symbols remain")
            try:
                doit = result.doit()
                if doit == sympy.true or doit == sympy.S.true:
                    return True
                if doit == sympy.false or doit == sympy.S.false:
                    return False
                return bool(doit)
            except Exception:
                return bool(result)
    except Exception:
        pass
    python_expr = expr.replace("^", "**")
    safe: dict[str, Any] = {
        "factorial": math.factorial,
        "is_prime": _is_prime_verify,
        "isprime": _is_prime_verify,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "exp": math.exp,
        "log": math.log,
        "Abs": abs,
        "abs": abs,
    }
    safe.update(assignment)
    return eval(python_expr, {"__builtins__": {}}, safe)  # noqa: S307


def _eval_set_verify(expr: str, assignment: dict[str, Any], set_vars: list[str]) -> Any:
    translated = _translate_set_verify(expr, set_vars)
    safe: dict[str, Any] = {
        "card": len,
        "sumset": _sumset,
        "subset": lambda a, b: a.issubset(b),
        "len": len,
        "factorial": math.factorial,
        "is_prime": _is_prime_verify,
        "isprime": _is_prime_verify,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "exp": math.exp,
        "log": math.log,
        "Abs": abs,
        "abs": abs,
    }
    safe.update(assignment)
    return eval(translated, {"__builtins__": {}}, safe)  # noqa: S307


def _evaluate_conclusion_verify(card: ClaimCard, assignment: dict[str, Any]) -> bool:
    expr = card.conclusion.expr
    if card.set_vars:
        return bool(_eval_set_verify(expr, assignment, card.set_vars))
    return bool(_eval_numeric_verify(expr, assignment))


def _evaluate_hypotheses_verify(card: ClaimCard, assignment: dict[str, Any]) -> bool:
    if not card.hypotheses:
        return True
    for h in card.hypotheses:
        if card.set_vars:
            if not bool(_eval_set_verify(h, assignment, card.set_vars)):
                return False
        else:
            if not bool(_eval_numeric_verify(h, assignment)):
                return False
    return True


def verify_counterexample(card: ClaimCard, assignment: dict[str, Any]) -> tuple[bool, str]:
    """Re-verify counterexample independently (second code path)."""
    try:
        hyp = _evaluate_hypotheses_verify(card, assignment)
        conc = _evaluate_conclusion_verify(card, assignment)
        valid = hyp and not conc
    except Exception as e:
        return False, f"verify error: {e}"
    if valid:
        return True, "verified: hypotheses hold and conclusion false"
    try:
        hyp = _evaluate_hypotheses_verify(card, assignment)
        conc = _evaluate_conclusion_verify(card, assignment)
        if not hyp:
            return False, "hypotheses false — not a counterexample (vacuous)"
        if conc:
            return False, "conclusion true — not a counterexample"
        return False, "unknown reason not counterexample"
    except Exception as e:
        return False, f"diagnose error: {e}"
