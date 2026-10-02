"""Find a file dropped from Finder on disk, from what the browser does tell us.

A browser never reveals a dropped file's path, but it does give its name, size
and last-modified time. Those three together pick out one file: Spotlight
finds candidates by name (it indexes the ChrisX drive), and size + mtime
choose among bounces that share a name ("song.mp3" is in every month folder).
If Spotlight doesn't know the file, a bounded walk of the usual folders runs.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

from .config import SEARCH_ROOTS

MTIME_SLACK_MS = 2000  # filesystems round mtimes; browsers report milliseconds
WALK_BUDGET_S = 4.0


def _matches(path: Path, size: int, mtime_ms: float) -> bool:
    try:
        stat = path.stat()
    except OSError:
        return False
    return path.is_file() and stat.st_size == size and abs(stat.st_mtime * 1000 - mtime_ms) <= MTIME_SLACK_MS


def _spotlight(name: str) -> list[Path]:
    query = 'kMDItemFSName == "' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    try:
        out = subprocess.run(["mdfind", query], capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [Path(line) for line in out.splitlines() if line.strip()]


def _walk(name: str, roots: list[str]) -> list[Path]:
    found: list[Path] = []
    deadline = time.monotonic() + WALK_BUDGET_S
    for root in roots:
        base = Path(root).expanduser()
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in ("node_modules", "Library")]
            if name in filenames:
                found.append(Path(dirpath) / name)
            if time.monotonic() > deadline:
                return found
    return found


def locate(name: str, size: int, mtime_ms: float, roots: list[str] | None = None) -> list[Path]:
    """Every file on disk that is this dropped file. Usually one; empty if it can't be found."""
    if not name or "/" in name:
        return []
    exact = [p for p in _spotlight(name) if _matches(p, size, mtime_ms)]
    if not exact:
        exact = [p for p in _walk(name, roots or SEARCH_ROOTS) if _matches(p, size, mtime_ms)]
    # The same bounce copied elsewhere: prefer the one in MuZik, then the shortest path.
    return sorted(set(exact), key=lambda p: ("/MuZik/" not in str(p), len(str(p))))
