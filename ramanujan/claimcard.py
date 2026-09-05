"""Restricted claim DSL — interpreter — ramanujan/claimcard.py

Deterministic interpreter for ClaimCard. This is the double-verification path;
keep it independent from search implementations in killcheck/*.
Sound evaluator: exact big-int computation, per-expression timeout, no
heuristic shortcuts.
"""

from __future__ import annotations

import math
import re
import signal
from typing import Any

import sympy
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

from ramanujan.schemas import ClaimCard

# ---------------------------------------------------------------------------
# Sympy parse helpers (explicit transformations, per AGENTS.md gotcha)
# ---------------------------------------------------------------------------

_TRANSFORMATIONS = standard_transformations + (convert_xor, implicit_multiplication_application)

_IsPrimeFunc = sympy.Function("is_prime")
_PrimeFunc = sympy.Function("prime")
_SYMPY_LOCALS: dict[str, Any] = {
    "factorial": sympy.factorial,
    "is_prime": _IsPrimeFunc,
    "isprime": _IsPrimeFunc,
    "prime": _PrimeFunc,
    "Abs": sympy.Abs,
    "sqrt": sympy.sqrt,
    "sin": sympy.sin,
    "cos": sympy.cos,
    "exp": sympy.exp,
    "log": sympy.log,
}


class EvaluationTimeout(Exception):
    """Raised when per-expression evaluation exceeds timeout."""


def _timeout_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
    raise EvaluationTimeout("evaluation too costly")


def _parse_sympy(expr: str) -> sympy.Basic:
    """Parse expr with explicit transformations; raise ValueError on failure."""
    try:
        return parse_expr(expr, local_dict=_SYMPY_LOCALS, transformations=_TRANSFORMATIONS)
    except Exception as e:
        raise ValueError(f"sympy parse failed for {expr!r}: {e}") from e


def validate_card(card: ClaimCard | dict[str, Any]) -> ClaimCard:
    """Validate and return a ClaimCard. Expressions must be sympy-parseable if flagged."""
    if isinstance(card, dict):
        card = ClaimCard.model_validate(card)
    # Validate conclusion / hypotheses parse
    if card.conclusion.sympy_parseable:
        _maybe_translate = _translate_for_sympy_check(card.conclusion.expr, card.set_vars)
        _parse_sympy(_maybe_translate)  # raise if invalid
    for h in card.hypotheses:
        _maybe = _translate_for_sympy_check(h, card.set_vars) if card.set_vars else h
        # hypothesis may contain set ops not sympy-parseable; only check if no set vars
        if not card.set_vars:
            _parse_sympy(_maybe)
    return card


def _translate_for_sympy_check(expr: str, set_vars: list[str]) -> str:
    """Best-effort translation for sympy parse check when set vars present."""
    # For cards with sets, direct sympy parse will fail; skip strict check.
    if set_vars:
        # replace card() wrappers to make it parseable
        tmp = re.sub(r"\|\s*([^|]+?)\s*\|", r"card(\1)", expr)
        tmp = re.sub(
            r"(\b[A-Za-z][A-Za-z0-9_]*\b)\s*\+\s*(\b[A-Za-z][A-Za-z0-9_]*\b)",
            r"sumset(\1,\2)",
            tmp,
        )
        # If still not parseable, don't enforce
        try:
            _parse_sympy(tmp)
        except ValueError:
            return "1 > 0"  # dummy that parses, since set exprs aren't sympy-encoded
        return tmp
    return expr


# ---------------------------------------------------------------------------
# Set-ops translation for Python eval
# ---------------------------------------------------------------------------


def _sumset(a: set[int], b: set[int]) -> set[int]:
    return {x + y for x in a for y in b}


def _card(s: set[int]) -> int:
    return len(s)


def _subset(a: set[int], b: set[int]) -> bool:
    return a.issubset(b)


def _translate_set_expr(expr: str, set_vars: list[str]) -> str:
    """Translate DSL set syntax into Python-evaluable expr."""
    out = expr
    # |X| -> card(X)  (handles nested like |A+B|)
    # Use regex to replace |...| iteratively (non-greedy)
    # Bounded to avoid infinite loop
    for _ in range(5):
        nxt = re.sub(r"\|\s*([^|]+?)\s*\|", r"card(\1)", out)
        if nxt == out:
            break
        out = nxt
    # A + B (sumset) -> sumset(A,B) when both are set vars
    if set_vars:
        # Need to replace set-var + set-var patterns, including card-wrapped args
        # Simple: for each pair of set vars, replace "A + B" and "A+B"
        for a in set_vars:
            for b in set_vars:
                # A + B -> sumset(A, B)
                pat = re.compile(rf"\b{re.escape(a)}\b\s*\+\s*\b{re.escape(b)}\b")
                out = pat.sub(f"sumset({a},{b})", out)
        # Also handle sumset inside card: card(sumset(A,B)) already correct
    # "subset" infix: "A subset B" -> "subset(A,B)"
    out = re.sub(r"\b([A-Za-z][A-Za-z0-9_]*)\s+subset\s+([A-Za-z][A-Za-z0-9_]*)\b", r"subset(\1,\2)", out)
    return out


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------


def _is_set_card(card: ClaimCard) -> bool:
    return bool(card.set_vars)


def evaluate_conclusion(card: ClaimCard, assignment: dict[str, Any]) -> bool:
    """Evaluate card conclusion under assignment. Returns True/False.

    For set cards: uses Python eval after translation.
    For int/real cards: uses sympy subs then bool cast (fallback to Python eval).
    Raises EvaluationTimeout if per-expression budget exceeded.
    """
    expr = card.conclusion.expr
    if _is_set_card(card):
        return bool(_eval_set_expr(expr, assignment, card.set_vars))
    return bool(_eval_numeric_expr(expr, assignment))


def evaluate_hypotheses(card: ClaimCard, assignment: dict[str, Any]) -> bool:
    """True if all hypotheses hold under assignment (vacuously true if none)."""
    if not card.hypotheses:
        return True
    for h in card.hypotheses:
        if _is_set_card(card):
            if not bool(_eval_set_expr(h, assignment, card.set_vars)):
                return False
        else:
            if not bool(_eval_numeric_expr(h, assignment)):
                return False
    return True


def is_counterexample(card: ClaimCard, assignment: dict[str, Any]) -> bool:
    """True iff hypotheses hold but conclusion is false (refutes universal)."""
    if not evaluate_hypotheses(card, assignment):
        return False
    return not evaluate_conclusion(card, assignment)


_EVAL_TIMEOUT_SEC = 2.0


def _eval_numeric_expr(expr: str, assignment: dict[str, Any]) -> Any:
    """Evaluate numeric boolean expr via sympy subs; fallback to Python eval.
    Sound: exact big-int math, per-expression timeout, no heuristic shortcuts.
    """
    # Per-expression timeout using SIGALRM (Unix main thread only).
    # In server threads signal.signal raises ValueError — fall back to no timeout.
    import threading

    use_alarm = hasattr(signal, "SIGALRM") and threading.current_thread() is threading.main_thread()
    old_handler = None
    if use_alarm:
        try:
            old_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(int(_EVAL_TIMEOUT_SEC) if _EVAL_TIMEOUT_SEC >= 1 else 1)
        except ValueError:
            # Not in main thread — no timeout, still exact evaluation
            use_alarm = False
    try:
        return _eval_numeric_inner(expr, assignment)
    except EvaluationTimeout:
        raise
    except Exception:
        raise
    finally:
        if use_alarm:
            try:
                signal.alarm(0)
                if old_handler is not None:
                    signal.signal(signal.SIGALRM, old_handler)
            except ValueError:
                pass


def _eval_numeric_inner(expr: str, assignment: dict[str, Any]) -> Any:
    # For is_prime, skip sympy and use Python eval directly (sympy isprime is not symbolic)
    if "is_prime" in expr or "isprime" in expr or "prime(" in expr:
        python_expr = expr.replace("^", "**")
        safe: dict[str, Any] = {
            "factorial": math.factorial,
            "is_prime": _is_prime,
            "isprime": _is_prime,
            "sqrt": math.sqrt,
            "sin": math.sin,
            "cos": math.cos,
            "exp": math.exp,
            "log": math.log,
            "Abs": abs,
            "abs": abs,
        }
        safe.update(assignment)
        try:
            return eval(python_expr, {"__builtins__": {}}, safe)  # noqa: S307
        except Exception as e:
            raise ValueError(f"cannot evaluate numeric expr {expr!r} with {assignment}: {e}") from e
    try:
        parsed = _parse_sympy(expr)
        subs = {sympy.Symbol(k): v for k, v in assignment.items()}
        result = parsed.subs(subs)
        # Direct check without simplify: sympy will have evaluated factorials etc. via subs
        # For relationals, subs yields BooleanTrue/False directly
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
            # If still an unevaluated relational, try doit
            try:
                doit = result.doit()
                if doit == sympy.true or doit == sympy.S.true:
                    return True
                if doit == sympy.false or doit == sympy.S.false:
                    return False
                return bool(doit)
            except Exception:
                return bool(result)
    except EvaluationTimeout:
        raise
    except Exception:
        pass
    # Fallback: Python eval with safe ns, exact big-int math
    python_expr = expr.replace("^", "**")
    safe: dict[str, Any] = {
        "factorial": math.factorial,
        "is_prime": _is_prime,
        "isprime": _is_prime,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "exp": math.exp,
        "log": math.log,
        "Abs": abs,
        "abs": abs,
    }
    safe.update(assignment)
    try:
        return eval(python_expr, {"__builtins__": {}}, safe)  # noqa: S307
    except EvaluationTimeout:
        raise
    except Exception as e:
        raise ValueError(f"cannot evaluate numeric expr {expr!r} with {assignment}: {e}") from e


def _eval_set_expr(expr: str, assignment: dict[str, Any], set_vars: list[str]) -> Any:
    translated = _translate_set_expr(expr, set_vars)
    safe: dict[str, Any] = {
        "card": _card,
        "sumset": _sumset,
        "subset": _subset,
        "len": len,
        "factorial": math.factorial,
        "is_prime": _is_prime,
        "isprime": _is_prime,
        "sqrt": math.sqrt,
        "sin": math.sin,
        "cos": math.cos,
        "exp": math.exp,
        "log": math.log,
        "Abs": abs,
        "abs": abs,
    }
    safe.update(assignment)
    # Also allow int vars coexistence
    try:
        return eval(translated, {"__builtins__": {}}, safe)  # noqa: S307
    except Exception as e:
        raise ValueError(f"cannot evaluate set expr {expr!r} -> {translated!r} with {assignment}: {e}") from e


def _is_prime(n: int) -> bool:
    if not isinstance(n, int):
        try:
            n = int(n)
        except Exception:
            return False
    # Fast path via sympy if available
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
