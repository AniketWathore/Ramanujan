"""Webtool wrapper for Ramanujan literature — ramanujan/webtool_client.py

Uses `agent-webtool` (potato47/agent-webtool) via npx for fetch/search.
No API keys, multi-engine (Baidu/WeChat/Toutiao/DuckDuckGo) with RRF.

Lookup:
  WEBTOOL_BIN env > npx agent-webtool > webtool on PATH > local dist
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _webtool_cmd() -> list[str] | None:
    # Env override
    env_bin = os.environ.get("WEBTOOL_BIN") or os.environ.get("AGENT_WEBTOOL_BIN")
    if env_bin:
        p = Path(env_bin)
        if p.is_file() and os.access(p, os.X_OK):
            return [str(p)]
        # assume it's a command string
        return env_bin.split()
    # Try npx
    if shutil.which("npx"):
        # Check if agent-webtool is available via npx
        try:
            # quick check: npx --yes agent-webtool --version
            res = subprocess.run(
                ["npx", "-y", "agent-webtool", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if res.returncode == 0:
                return ["npx", "-y", "agent-webtool"]
        except Exception:
            pass
    if shutil.which("webtool"):
        return ["webtool"]
    if shutil.which("agent-webtool"):
        return ["agent-webtool"]
    # Local build fallback
    local = Path(__file__).parent.parent / "agent-webtool-main" / "dist" / "cli.mjs"
    if local.is_file():
        return ["node", str(local)]
    return None


def is_available() -> bool:
    return _webtool_cmd() is not None


def fetch(url: str, fmt: str = "markdown", max_bytes: int = 100000, timeout: int = 30, raw: bool = True) -> str:
    """Fetch URL via webtool fetch. Returns markdown/text/html. Raises on failure."""
    cmd = _webtool_cmd()
    if not cmd:
        raise FileNotFoundError("webtool not found — run npm install agent-webtool or set WEBTOOL_BIN")
    args = [*cmd, "fetch", url, "--format", fmt, "--max-bytes", str(max_bytes), "--timeout-ms", str(timeout * 1000)]
    if raw:
        args.append("--raw")
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        # Check for redirect hint
        if "Redirected to a different host" in result.stdout:
            # Extract redirect URL and retry
            m = re.search(r"https://[^\s\]]+", result.stdout)
            if m:
                return fetch(m.group(0), fmt=fmt, max_bytes=max_bytes, timeout=timeout, raw=raw)
        raise RuntimeError(f"webtool fetch failed ({result.returncode}): {result.stderr[:500]} {result.stdout[:500]}")
    return result.stdout


def search(query: str, limit: int = 10, engines: str = "duckduckgo", timeout: int = 30, raw: bool = True) -> dict[str, Any]:
    """Search via webtool search. Returns dict with text, results, engines status."""
    cmd = _webtool_cmd()
    if not cmd:
        raise FileNotFoundError("webtool not found")
    args = [*cmd, "search", query, "--limit", str(limit), "--engines", engines, "--timeout-ms", str(timeout * 1000)]
    if raw:
        args.append("--raw")
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout + 10)
    if result.returncode != 0:
        raise RuntimeError(f"webtool search failed ({result.returncode}): {result.stderr[:500]}")
    text = result.stdout
    # Parse citation list: [1] Title\nhttps://url\nSnippet
    results: list[dict[str, Any]] = []
    # Split by citation markers
    pattern = re.compile(r"\[(\d+)\]\s*(.+?)\n(https?://[^\s]+)\n([^\[]*?)(?=\n\[\d+\]|\n> Note:|\Z)", re.DOTALL)
    for m in pattern.finditer(text):
        idx, title, url, snippet = m.groups()
        title = title.strip()
        url = url.strip()
        snippet = snippet.strip()
        # Clean up title from snippet overlap
        results.append({"title": title, "url": url, "snippet": snippet, "index": int(idx)})
    # Fallback: simple line parsing if regex fails
    if not results:
        lines = text.split("\n")
        cur: dict[str, Any] | None = None
        for line in lines:
            line = line.strip()
            if not line or line.startswith("> Note:") or line.startswith("No results"):
                continue
            m = re.match(r"\[(\d+)\]\s*(.+)", line)
            if m:
                if cur:
                    results.append(cur)
                cur = {"title": m.group(2).strip(), "url": "", "snippet": "", "index": int(m.group(1))}
            elif cur and line.startswith("http"):
                cur["url"] = line
            elif cur and cur.get("url"):
                cur["snippet"] = (cur.get("snippet", "") + " " + line).strip()
        if cur and cur.get("url"):
            results.append(cur)
    return {"text": text, "results": results, "raw": text}


def fetch_via_webtool_or_fallback(url: str, timeout: int = 15) -> str | None:
    """Best-effort fetch via webtool, fallback to urllib. Never raises."""
    try:
        if is_available():
            return fetch(url, fmt="markdown", timeout=timeout)
    except Exception:
        pass
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "Ramanujan/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")[:20000]
    except Exception:
        return None
