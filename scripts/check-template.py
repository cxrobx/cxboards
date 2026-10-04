#!/usr/bin/env python3
"""Check template files one by one, without needing the rest of the library to be valid.

    .venv/bin/python scripts/check-template.py templates/podcasting/*.yaml

For each file: it parses and follows the format, its slug, name and source aren't used by any other
template file, and it builds into a board (in a throwaway database) with no cards overlapping.
Prints one line per file; exits non-zero if any failed. tests/test_templates.py checks the whole
library the same way.
"""

from __future__ import annotations

import itertools
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cxboards import templates as lib  # noqa: E402
from cxboards.config import Config  # noqa: E402
from cxboards.layout import Rect  # noqa: E402
from cxboards.store import Store  # noqa: E402

LIBRARY = ROOT / "templates"


def others(skip: Path) -> list[tuple[Path, dict]]:
    out = []
    for path in sorted(LIBRARY.glob("*/*.yaml")):
        if path.resolve() == skip.resolve():
            continue
        try:
            raw = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError:
            continue
        if isinstance(raw, dict):
            out.append((path, raw))
    return out


def overlaps(store: Store, board_id: str) -> list[str]:
    cards = [c for c in store.cards(board_id) if not c["column_id"] and not c["tray"]]
    rects = {c["id"]: Rect(c["x"], c["y"], c["w"], c["h"]) for c in cards}
    bad = [f"{a} overlaps {b}" for (a, ra), (b, rb) in itertools.combinations(rects.items(), 2) if ra.overlaps(rb, gap=0)]
    for c in cards:
        if c["kind"] == "board":
            bad += overlaps(store, c["data"]["board_id"])
    return bad


def check(path: Path, store: Store, categories: set[str]) -> str | None:
    category = path.parent.name
    if category not in categories:
        return f"{category}/ isn't a category in templates/categories.yaml"
    if not lib.SLUG.fullmatch(path.stem):
        return "file names are lowercase-with-dashes"
    t = lib.parse(path, category)
    for other, raw in others(path):
        if other.stem == t.slug:
            return f"the slug {t.slug} is already {other.parent.name}/{other.name}"
        if str(raw.get("name", "")).strip().lower() == t.name.lower():
            return f"the name {t.name!r} is already {other.parent.name}/{other.name}"
        if t.source and str(raw.get("source", "")).rstrip("/").lower() == t.source.rstrip("/").lower():
            return f"{t.source} is already the source of {other.parent.name}/{other.name}"
    for a in t.also:
        if a not in categories or a == category:
            return f"also lists {a!r}, which isn't another category"
    board = store.build_board(t.name, lib.plan(t.cards), theme=t.theme)
    bad = overlaps(store, board["id"])
    return "; ".join(bad) if bad else None


def main(paths: list[str]) -> int:
    categories = {c["slug"] for c in yaml.safe_load((LIBRARY / "categories.yaml").read_text())}
    failed = 0
    with tempfile.TemporaryDirectory() as home:
        store = Store(Config(home=Path(home), port=0))
        for name in paths:
            path = Path(name)
            try:
                problem = check(path, store, categories)
            except lib.TemplateError as e:
                problem = str(e)
            except Exception as e:  # a build error is still this file's problem
                problem = f"{type(e).__name__}: {e}"
            failed += bool(problem)
            print(f"{'✗' if problem else '✓'} {path.parent.name}/{path.name}" + (f" — {problem}" if problem else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]) if len(sys.argv) > 1 else print(__doc__) or 2)
