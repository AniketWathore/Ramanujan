"""Stage 2 Literature agent — ramanujan/literature.py (v2 Phase 2).

Surveys prior work for a problem and produces a structured papers index plus a
short synthesis (never a raw dump). Checkpoint B presents the synthesis.

Provenance rule (Build Brief §4.4, STRUCTURAL not prompt-luck): every
`PaperEntry` carries either a real `source_url` or an explicit
`"provenance": "model-memory, unverified"` tag, enforced by a pydantic
model validator — an unmarked hallucinated citation can never validate,
so downstream stages can treat the index as ground truth about what is
and isn't known.

Three-way contract (mirrors encoder/initialiser — never conflate refusal
with system failure):
- `index` — papers index (+ synthesis) produced. May be EMPTY (keyless
  runs cannot search); emptiness is honest, not an error.
- `not_searchable` — the model itself explicitly refused (NOT_SEARCHABLE).
- `literature_error` — model failure, timeout, or validation failure after
  retries. Never rendered as "no prior work exists".
"""

from __future__ import annotations

import contextlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

#: The exact tag uncited model recall must carry. No exceptions.
UNVERIFIED_PROVENANCE: Literal["model-memory, unverified"] = "model-memory, unverified"


class PaperEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    id: str = Field(pattern=r"^lit_\d+$")
    title: str = Field(min_length=1)
    authors: list[str] = Field(default_factory=list)
    year: int | None = Field(default=None, ge=1000, le=3000)
    source_url: str | None = None
    provenance: str = Field(default=UNVERIFIED_PROVENANCE)
    relevance: str = Field(min_length=1, description="why this matters for the problem")
    note: str = Field(default="", description="markdown body for papers/<id>.md")

    @model_validator(mode="after")
    def check_provenance(self) -> PaperEntry:
        # §4.4: real URL xor explicit unverified tag. An entry with neither,
        # or with a non-URL source passed off as retrieved, never validates.
        if self.source_url:
            if self.provenance != "retrieved":
                raise ValueError(f"entry {self.id}: source_url present but provenance is {self.provenance!r} — must be 'retrieved'")
        elif self.provenance != UNVERIFIED_PROVENANCE:
            raise ValueError(f"entry {self.id}: no source_url and provenance is {self.provenance!r} — must be {UNVERIFIED_PROVENANCE!r}")
        return self


class PapersIndex(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    papers: list[PaperEntry] = Field(default_factory=list)
    # Short synthesis, not a raw dump — this is what Checkpoint B presents.
    synthesis: str = Field(min_length=1)


LITERATURE_SYSTEM = """You are the Ramanujan Literature agent. Survey prior work relevant to the problem.

You MUST output STRICT JSON matching schema exactly — no markdown:

{
  "papers": [
    {"title": "<paper or known result>",
     "authors": ["<names, if known>"],
     "year": <year or null>,
     "source_url": "<real retrieval URL, or null when recalling from memory>",
     "provenance": "retrieved | model-memory, unverified",
     "relevance": "<one or two sentences: why this matters for the problem>",
     "note": "<short markdown note for the papers file>"}
  ],
  "synthesis": "<short synthesis paragraph: what is known, what is open — NOT a raw dump>"
}

Rules:
- "retrieved" means you actually have the source in context (tool output, provided text). NEVER mark recalled-from-memory items as retrieved.
- Anything from memory gets "source_url": null and "provenance": "model-memory, unverified" — no exceptions. An unmarked hallucinated citation poisons every downstream stage.
- Prefer fewer, relevant entries over a long padded list. An empty list is honest when nothing relevant is known.
- If the problem has no searchable content (meaningless, not mathematics): {"error": "NOT_SEARCHABLE", "reason": "<why>"}
  ONLY refuse yourself when there is truly nothing to survey.
  NEVER emit NOT_SEARCHABLE because of a validation error — fix the JSON instead.
- Temperature 0, precise.
"""


def _extract_json(text: str) -> str:
    """Extract JSON object from LLM text (strip markdown fences)."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, flags=re.DOTALL)
    if m:
        return m.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _balanced_candidates(text: str) -> list[str]:
    """All top-level balanced {...} spans, longest first.

    Reasoning models emit chain-of-thought before the answer; first-{-to-last-}
    then spans thinking + JSON + trailing prose and never parses. The final
    answer is usually the largest balanced block, so try longest first.
    String-aware: braces inside "..." don't count.
    """
    spans: list[str] = []
    i, n = 0, len(text)
    while i < n:
        if text[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        j = i
        while j < n:
            ch = text[j]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    spans.append(text[i : j + 1])
                    break
            j += 1
        i = j + 1 if j < n and depth == 0 else i + 1
    spans.sort(key=len, reverse=True)
    return spans


def _parse_first_valid(text: str) -> dict[str, Any]:
    """Parse the first candidate that is a JSON object; fence fast-path first."""
    try:
        parsed = json.loads(_extract_json(text))
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    for cand in _balanced_candidates(text):
        try:
            parsed = json.loads(cand)
        except Exception:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("no JSON object found in model output")


class LiteratureResult:
    """Three-way outcome: index | not_searchable | literature_error."""

    def __init__(self, index: PapersIndex | None, error: str | None, attempts: int) -> None:
        self.index = index
        self.error = error
        self.attempts = attempts
        self.is_not_searchable = error is not None and "NOT_SEARCHABLE" in error

    @property
    def success(self) -> bool:
        return self.index is not None

    @property
    def is_literature_error(self) -> bool:
        return not self.success and not self.is_not_searchable

    @property
    def status(self) -> str:
        if self.success:
            return "index"
        if self.is_not_searchable:
            return "not_searchable"
        return "literature_error"


def _empty_index(reason: str) -> PapersIndex:
    return PapersIndex(
        papers=[],
        synthesis=(
            "No literature search performed: " + reason + " Treat all downstream "
            "claims as ungrounded in prior work until a keyed survey runs."
        ),
    )


def survey_literature(
    statement: str,
    *,
    journal: Any | None = None,
    caller=None,
    model_spec=None,
    spec_context: str = "",
    max_retries: int = 3,
) -> LiteratureResult:
    """Survey prior work. `caller` is a call_llm-compatible injection (tests);
    None means a real call. `model_spec` None → honest empty index (keyless).

    Entry ids are assigned deterministically (lit_001…) in listed order.
    """
    if model_spec is None:
        return LiteratureResult(index=_empty_index("no LLM key resolved"), error=None, attempts=0)

    from ramanujan.providers import call_llm

    context_block = f"\nStructured spec context:\n{spec_context}\n" if spec_context else ""
    messages = [
        {"role": "system", "content": LITERATURE_SYSTEM},
        {"role": "user", "content": f"Problem to survey:\n{statement}\n{context_block}\nOutput strict JSON only."},
    ]
    attempts = 0
    last_error = ""
    last_raw = ""
    for _attempt in range(max_retries):
        attempts += 1
        try:
            resp = call_llm(model_spec, messages, journal=journal, caller=caller)
            raw_text = resp["text"]
        except Exception as e:
            last_error = f"LLM call failed: {e}"
            continue
        last_raw = raw_text
        try:
            parsed = _parse_first_valid(raw_text)
        except Exception as e:
            last_error = f"JSON parse error: {e}"
            messages.append({"role": "assistant", "content": raw_text})
            messages.append({"role": "user", "content": f"Validation error: {last_error}\nOutput strict JSON matching the schema."})
            continue
        if isinstance(parsed, dict) and parsed.get("error") == "NOT_SEARCHABLE":
            reason = parsed.get("reason", "not searchable")
            return LiteratureResult(index=None, error=f"NOT_SEARCHABLE: {reason}", attempts=attempts)
        try:
            raw_papers = parsed.get("papers", [])
            if not isinstance(raw_papers, list):
                raise ValueError("papers must be a list")
            entries = []
            for i, p in enumerate(raw_papers, start=1):
                if not isinstance(p, dict):
                    raise ValueError(f"paper #{i} must be an object")
                entries.append(
                    PaperEntry(
                        id=f"lit_{i:03d}",
                        title=p.get("title", ""),
                        authors=list(p.get("authors", [])),
                        year=p.get("year"),
                        source_url=p.get("source_url"),
                        provenance=p.get("provenance", UNVERIFIED_PROVENANCE),
                        relevance=p.get("relevance", ""),
                        note=p.get("note", ""),
                    )
                )
            synthesis = parsed.get("synthesis", "")
            if not isinstance(synthesis, str) or not synthesis.strip():
                raise ValueError("synthesis must be a non-empty string")
            index = PapersIndex(papers=entries, synthesis=synthesis.strip())
        except Exception as e:
            last_error = f"index validation failed: {e}"
            messages.append({"role": "assistant", "content": last_raw})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Validation error: {last_error}\nFix the JSON: every paper needs "
                        "source_url or provenance 'model-memory, unverified', plus a non-empty synthesis."
                    ),
                }
            )
            continue
        if journal is not None:
            for entry in index.papers:
                with contextlib.suppress(Exception):
                    journal.write(
                        "literature_entry_added",
                        {
                            "lit_id": entry.id,
                            "title": entry.title,
                            "provenance": entry.provenance,
                            "has_url": entry.source_url is not None,
                        },
                    )
        return LiteratureResult(index=index, error=None, attempts=attempts)
    return LiteratureResult(index=None, error=last_error or "survey failed", attempts=attempts)
