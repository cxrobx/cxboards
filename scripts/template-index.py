#!/usr/bin/env python3
"""Write the catalogue section of templates/README.md from the library itself.

    .venv/bin/python scripts/template-index.py          # rewrite it
    .venv/bin/python scripts/template-index.py --check  # exit 1 if it's out of date (tests/test_templates.py)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from cxboards import templates as lib  # noqa: E402

README = ROOT / "templates" / "README.md"
START, END = "<!-- index:start -->", "<!-- index:end -->"


def index(cat: lib.Catalog) -> str:
    lines = [START, "", f"**{len(cat.templates)} templates in {len(cat.categories)} use cases.** "
             "Each lives in exactly one folder; a template that serves another use case too is listed there in *italics*.", ""]
    for c in cat.categories:
        own = sorted((t for t in cat.templates.values() if t.category == c["slug"]), key=lambda t: t.name.lower())
        shared = sorted((t for t in cat.templates.values() if c["slug"] in t.also), key=lambda t: t.name.lower())
        if not own and not shared:
            continue
        lines += [f"### {c['name']}", "", c["blurb"], "", "| Template | Use it when | Slug |", "|---|---|---|"]
        for t in own:
            lines.append(f"| [{t.name}]({t.category}/{t.slug}.yaml) | {t.use_when} | `{t.slug}` |")
        for t in shared:
            lines.append(f"| *[{t.name}]({t.category}/{t.slug}.yaml)* | {t.use_when} | `{t.slug}` |")
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def render() -> str:
    text = README.read_text()
    head, rest = text.split(START, 1)
    tail = rest.split(END, 1)[1]
    return head + index(lib.load()) + tail


if __name__ == "__main__":
    fresh = render()
    if "--check" in sys.argv:
        ok = README.read_text() == fresh
        print("templates/README.md is up to date" if ok else "templates/README.md is out of date: run scripts/template-index.py")
        sys.exit(0 if ok else 1)
    README.write_text(fresh)
    print(f"wrote {README.relative_to(ROOT)}")
