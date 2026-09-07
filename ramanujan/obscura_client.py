"""Obscura wrapper for Ramanujan literature — ramanujan/obscura_client.py

Single call site for the bundled headless browser. Binary is looked up as:
  OBSCURA_BIN env > tools/obscura/bin/obscura (repo checkout, from scripts/install-obscura.sh)
         > obscura on PATH
The worker binary must sit next to it for `scrape` (README:165).

Only the capabilities literature needs are exposed: fetch --dump {text,markdown,links,html}
and scrape --concurrency. No stealth by default; pass stealth=True to add --stealth.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def _obscura_bin() -> str | None:
    for cand in [
        os.environ.get("OBSCURA_BIN"),
        os.environ.get("RAMANUJAN_OBSCURA_BIN"),
        str(Path(__file__).parent.parent / "tools" / "obscura" / "bin" / "obscura"),
        str(Path.cwd() / "tools" / "obscura" / "bin" / "obscura"),
        "obscura",
    ]:
        if not cand:
            continue
        p = Path(cand)
        # Bare name "obscura" — check PATH
        if cand == "obscura":
            import shutil
            if shutil.which("obscura"):
                return "obscura"
            continue
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    import shutil
    return shutil.which("obscura")

def is_available() -> bool:
    return _obscura_bin() is not None

def fetch(url: str, dump: str = "markdown", eval_js: str | None = None, timeout: int = 15, stealth: bool = False, extra_args: list[str] | None = None) -> str:
    """Fetch one URL via `obscura fetch`. Returns stdout text. Raises on failure."""
    bin_path = _obscura_bin()
    if not bin_path:
        raise FileNotFoundError("obscura binary not found — run scripts/install-obscura.sh or set OBSCURA_BIN")
    args = [bin_path, "fetch", url, "--dump", dump, "--timeout", str(timeout)]
    if eval_js:
        args += ["--eval", eval_js]
    if stealth:
        args.append("--stealth")
    if extra_args:
        args += extra_args
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        raise RuntimeError(f"obscura fetch failed ({result.returncode}): {result.stderr[:500]}")
    return result.stdout

def scrape(urls: list[str], dump: str = "markdown", concurrency: int = 5, timeout: int = 15, stealth: bool = False) -> list[dict[str, Any]]:
    """Parallel scrape via `obscura scrape`. Returns list of {url, content} parsed from JSON lines."""
    bin_path = _obscura_bin()
    if not bin_path:
        raise FileNotFoundError("obscura binary not found")
    args = [bin_path, "scrape", *urls, "--concurrency", str(concurrency), "--dump", dump, "--format", "json", "--timeout", str(timeout)]
    if stealth:
        args.append("--stealth")
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 20)
    if result.returncode != 0:
        raise RuntimeError(f"obscura scrape failed: {result.stderr[:500]}")
    out: list[dict[str, Any]] = []
    for line in result.stdout.splitlines():
        line=line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            out.append({"url": urls[0] if urls else "", "content": line})
    return out

def fetch_via_obscura_or_fallback(url: str, timeout: int = 15) -> str | None:
    """Best-effort: try obscura, fall back to urllib. Never raises."""
    try:
        if is_available():
            return fetch(url, dump="markdown", timeout=timeout)
    except Exception:
        pass
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Ramanujan/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")[:20000]
    except Exception:
        return None
