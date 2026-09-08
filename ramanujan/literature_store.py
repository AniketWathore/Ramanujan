"""File-based store for literature — per-session text files.

Each literature invocation creates / reuses:
  literature/data/session_{id}/
    papers.md
    websites.txt
    blogs.txt
    books.txt
    articles.txt
    pdfs.txt
    problems.txt
    solutions.txt
    discussions.txt
    synthesis.md
    metadata.json
    all_data.md

All content is fetched via Obscura (headless) and stored as text/markdown.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def get_session_dir(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id.strip())
    if not safe:
        safe = "unknown"
    return _repo_root() / "literature" / "data" / f"session_{safe}"


# Backward compat: old code called get_db_path, now returns session dir
def get_db_path(session_id: str) -> Path:
    return get_session_dir(session_id) / "literature.db"


def get_db_path_compat(session_id: str) -> Path:
    return get_session_dir(session_id) / "literature.db"


def _write_category_file(session_dir: Path, category: str, entries: list[dict[str, Any]]) -> Path:
    # map category to filename
    name_map = {
        "papers": "papers.md",
        "websites": "website_contents.txt",
        "blogs": "blogs.txt",
        "books": "books.txt",
        "articles": "articles.txt",
        "pdfs": "pdfs.txt",
        "problems": "problems.txt",
        "solutions": "solutions.txt",
        "discussions": "discussions.txt",
    }
    filename = name_map.get(category, f"{category}.txt")
    path = session_dir / filename
    # Build content
    lines: list[str] = []
    lines.append(f"# {category.upper()} — {len(entries)} entries")
    lines.append(f"Generated: {datetime.now(timezone.utc).isoformat()}")
    lines.append("")
    for e in entries:
        lines.append("=" * 80)
        lines.append(f"ID: {e.get('id','')}")
        lines.append(f"Title: {e.get('title','')}")
        authors = e.get("authors", [])
        if isinstance(authors, list):
            authors = ", ".join(authors)
        lines.append(f"Authors: {authors}")
        lines.append(f"Year: {e.get('year','')}")
        lines.append(f"Source: {e.get('source_url','')}")
        lines.append(f"Provenance: {e.get('provenance','')}")
        lines.append(f"Category: {e.get('category', category)}")
        lines.append(f"Relevance: {e.get('relevance','')}")
        lines.append("")
        content = e.get("content") or e.get("note", "")
        lines.append(content.strip() if content else "(no content)")
        lines.append("")
        lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def store_session(
    session_id: str,
    statement: str,
    synthesis: str | None,
    *,
    run_id: str | None = None,
    provider: str | None = None,
    model_id: str | None = None,
    db_path: Path | None = None,
) -> Path:
    # db_path is now session_dir for compat
    session_dir = get_session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    meta = {
        "session_id": session_id,
        "statement": statement,
        "synthesis": synthesis,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "provider": provider,
        "model_id": model_id,
    }
    (session_dir / "metadata.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    if synthesis:
        (session_dir / "synthesis.md").write_text(f"# Synthesis\n\n{synthesis}\n", encoding="utf-8")
    # also write statement file
    (session_dir / "statement.txt").write_text(statement, encoding="utf-8")
    return session_dir


def store_entries(
    session_id: str,
    entries: list[dict[str, Any]],
    *,
    db_path: Path | None = None,
) -> Path:
    session_dir = get_session_dir(session_id)
    session_dir.mkdir(parents=True, exist_ok=True)
    # group by category
    by_cat: dict[str, list[dict[str, Any]]] = {}
    for e in entries:
        cat = e.get("category", "papers")
        # normalize
        cat = cat.lower()
        if cat not in ("papers", "websites", "blogs", "books", "articles", "pdfs", "problems", "solutions", "discussions"):
            # map website_contents etc
            if cat == "website":
                cat = "websites"
            elif cat == "website_contents":
                cat = "websites"
        by_cat.setdefault(cat, []).append(e)
    for cat, ents in by_cat.items():
        _write_category_file(session_dir, cat, ents)
    # also write all_data.md combined
    all_path = session_dir / "all_data.md"
    lines: list[str] = [f"# All Literature Data — Session {session_id}", f"Generated: {datetime.now(timezone.utc).isoformat()}", ""]
    for cat in sorted(by_cat.keys()):
        lines.append(f"## {cat.upper()} ({len(by_cat[cat])})")
        lines.append("")
        for e in by_cat[cat]:
            lines.append(f"### {e.get('title','')}")
            lines.append(f"- ID: {e.get('id','')}")
            lines.append(f"- Source: {e.get('source_url','')}")
            lines.append(f"- Category: {cat}")
            lines.append("")
            content = e.get("content") or e.get("note","")
            lines.append(content[:2000] + ("..." if len(content) > 2000 else ""))
            lines.append("")
    all_path.write_text("\n".join(lines), encoding="utf-8")
    return session_dir


def store_literature(
    session_id: str,
    statement: str,
    papers: list[Any],  # list[PaperEntry] or dicts
    synthesis: str,
    *,
    run_id: str | None = None,
    provider: str | None = None,
    model_id: str | None = None,
) -> Path:
    """Store a PapersIndex (or list of PaperEntry) into per-session files."""
    session_dir = get_session_dir(session_id)
    store_session(session_id, statement, synthesis, run_id=run_id, provider=provider, model_id=model_id, db_path=session_dir)
    dicts: list[dict[str, Any]] = []
    for p in papers:
        if hasattr(p, "model_dump"):
            d = p.model_dump()
            low = (d.get("relevance") or "").lower()
            cat = "papers"
            if "blog" in low:
                cat = "blogs"
            elif "book" in low:
                cat = "books"
            elif "discussion" in low:
                cat = "discussions"
            elif "website" in low or "duckduckgo" in low:
                cat = "websites"
            elif "article" in low:
                cat = "articles"
            elif "pdf" in low or (d.get("source_url") or "").lower().endswith(".pdf"):
                cat = "pdfs"
            elif "problem" in low:
                cat = "problems"
            elif "solution" in low:
                cat = "solutions"
            # try to preserve original content if was a web scrape dict
            # for model_dump entries, note already contains content (maybe truncated)
            d["category"] = cat
            d["content"] = d.get("note", "")
            d["fetched_at"] = datetime.now(timezone.utc).isoformat()
            dicts.append(d)
        elif isinstance(p, dict):
            p.setdefault("category", "papers")
            p.setdefault("content", p.get("note", ""))
            # normalize category
            cat = str(p.get("category", "papers")).lower()
            if cat == "website":
                cat = "websites"
            p["category"] = cat
            dicts.append(p)
    if dicts:
        store_entries(session_id, dicts, db_path=session_dir)
    else:
        # still create empty files for visibility
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "all_data.md").write_text(f"# All Literature Data — Session {session_id}\n\nNo entries.\n", encoding="utf-8")
    return session_dir


def get_session_stats(db_path: Path) -> dict[str, Any]:
    # db_path may be session dir or old .db path — handle both
    p = Path(db_path)
    session_dir = p if p.is_dir() else p.parent
    if not session_dir.exists():
        return {"exists": False}
    files = list(session_dir.glob("*.txt")) + list(session_dir.glob("*.md")) + list(session_dir.glob("*.json"))
    # count entries via all_data.md or metadata
    try:
        # try to count via files
        total = 0
        by_cat: dict[str, int] = {}
        for f in session_dir.glob("*.txt"):
            # approximate: count "ID:" lines
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
                c = txt.count("\nID: ")
                if c:
                    by_cat[f.stem] = c
                    total += c
            except Exception:
                pass
        for f in session_dir.glob("*.md"):
            try:
                txt = f.read_text(encoding="utf-8", errors="ignore")
                c = txt.count("\nID: ") + txt.count("\n### ")
                if c:
                    # already counted txt, avoid double
                    pass
            except Exception:
                pass
        return {"exists": True, "total": total, "by_category": by_cat, "path": str(session_dir), "files": [str(x.name) for x in files]}
    except Exception:
        return {"exists": True, "path": str(session_dir), "files": [str(x.name) for x in files] if session_dir.exists() else []}
