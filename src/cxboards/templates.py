"""The template library: boards described as files, filed by use case.

``templates/categories.yaml`` lists the categories in order; each template is
``templates/<category>/<slug>.yaml``. The slug is the template's name everywhere (the New board
dialog, ``create_board(template=...)``, ``list_templates``), so it is unique across the whole
library, and so are names and sources: one template per use, no duplicates.

A template file::

    name: Podcast episode plan
    use_when: Planning one episode, from the idea to the promotion after it.
    also: [content-creation]          # other categories it belongs to (optional)
    source: https://milanote.com/...  # what it was modelled on (optional)
    theme: film                       # a board theme preset (optional)
    cards:                            # in reading order, left to right
      - note: "# The episode\\nOne line on what the listener leaves with."
      - break                         # start a new row
      - column: Research
        cards:
          - note: Three sources worth quoting
          - todo: Before recording
            items: [Book the guest, Send questions]
      - swatch: "#E0A33A"
        text: Cover art accent
      - board: Guest notes            # a board inside the board
        cards: [...]

Cards are notes, to-dos, swatches, columns (of notes, to-dos and swatches) and boards. No
coordinates: ``plan`` lays the cards out in rows with ``layout.flow``, and ``Store.build_board``
writes the result as one transaction (one undo step).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import layout, themes

ROOT = Path(__file__).resolve().parents[2] / "templates"

# The card colours the board's colour picker offers (web/src/context.ts COLORS).
COLORS = {
    "amber": "#E0A33A",
    "clay": "#CB4B16",
    "green": "#859900",
    "cyan": "#2AA198",
    "violet": "#6C71C4",
    "magenta": "#D33682",
}

TEMPLATE_KEYS = {"name", "use_when", "also", "source", "theme", "cards"}
CARD_KEYS = {
    "note": {"note", "color", "width"},
    "todo": {"todo", "items", "color", "width"},
    "swatch": {"swatch", "text"},
    "column": {"column", "cards", "color", "width"},
    "board": {"board", "cards", "folder"},
}
IN_COLUMN = {"note", "todo", "swatch"}
MAX_DEPTH = 2  # a board inside a board inside the template, no deeper
SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class TemplateError(ValueError):
    """A template file that doesn't follow the format. The message names the file and the place."""


@dataclass(frozen=True)
class Template:
    slug: str
    category: str
    name: str
    use_when: str
    cards: list[Any]
    also: tuple[str, ...] = ()
    source: str | None = None
    theme: str | None = None
    path: Path | None = None

    def summary(self) -> dict[str, Any]:
        return {
            "slug": self.slug,
            "name": self.name,
            "category": self.category,
            "also": list(self.also),
            "use_when": self.use_when,
            "source": self.source,
            "theme": self.theme,
            "card_count": count_cards(self.cards),
            "preview": preview(self),
        }


@dataclass
class Catalog:
    categories: list[dict[str, Any]] = field(default_factory=list)
    templates: dict[str, Template] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)  # files left out (lenient loads only)

    def get(self, slug: str) -> Template | None:
        return self.templates.get((slug or "").strip().lower())

    def in_category(self, category: str) -> list[Template]:
        return [t for t in self.templates.values() if t.category == category or category in t.also]


# ---------------------------------------------------------------- validation

def _card_kind(card: Any, where: str) -> str:
    if card == "break":
        return "break"
    if not isinstance(card, dict):
        raise TemplateError(f"{where}: a card is a mapping like {{note: ...}} or the word break")
    kinds = [k for k in CARD_KEYS if k in card]
    if len(kinds) != 1:
        raise TemplateError(f"{where}: a card needs exactly one of {', '.join(CARD_KEYS)}")
    kind = kinds[0]
    extra = set(card) - CARD_KEYS[kind]
    if extra:
        raise TemplateError(f"{where}: a {kind} card can't have {', '.join(sorted(extra))}")
    return kind


def _check_cards(cards: Any, where: str, depth: int = 0, in_column: bool = False) -> None:
    if not isinstance(cards, list):
        raise TemplateError(f"{where}: cards is a list")
    for i, card in enumerate(cards):
        here = f"{where}[{i}]"
        kind = _card_kind(card, here)
        if kind == "break":
            if in_column:
                raise TemplateError(f"{here}: break only goes between cards on a board, not in a column")
            continue
        if in_column and kind not in IN_COLUMN:
            raise TemplateError(f"{here}: a column holds notes, to-dos and swatches, not a {kind}")
        if card.get("color") is not None and card["color"] not in COLORS:
            raise TemplateError(f"{here}: color is one of {', '.join(COLORS)}")
        if card.get("width") is not None and not (isinstance(card["width"], int) and 200 <= card["width"] <= 600):
            raise TemplateError(f"{here}: width is a whole number from 200 to 600")
        if kind == "note":
            if not isinstance(card["note"], str) or not card["note"].strip():
                raise TemplateError(f"{here}: a note needs text")
        elif kind == "todo":
            if not isinstance(card["todo"], str):
                raise TemplateError(f"{here}: todo is the list's title (\"\" for none)")
            items = card.get("items")
            if not isinstance(items, list) or not items:
                raise TemplateError(f"{here}: a to-do needs items")
            for item in items:
                text = item.get("text") if isinstance(item, dict) else item
                if not isinstance(text, str) or not text.strip():
                    raise TemplateError(f"{here}: each to-do item is text, or {{text, done, indent}}")
                if isinstance(item, dict) and set(item) - {"text", "done", "indent"}:
                    raise TemplateError(f"{here}: a to-do item has only text, done and indent")
                if re.search(r"\*\S|`", text):
                    raise TemplateError(f"{here}: to-do items are plain text; the board doesn't render markdown in them")
        elif kind == "swatch":
            if not isinstance(card["swatch"], str) or not re.fullmatch(r"#[0-9A-Fa-f]{6}", card["swatch"]):
                raise TemplateError(f"{here}: a swatch is a hex colour like \"#E0A33A\"")
            if "text" in card and not isinstance(card["text"], str):
                raise TemplateError(f"{here}: a swatch's text is a label")
        elif kind == "column":
            if not isinstance(card["column"], str) or not card["column"].strip():
                raise TemplateError(f"{here}: a column needs a title")
            if re.search(r"\*\S", card["column"]):
                raise TemplateError(f"{here}: a column title is plain text; the board doesn't render markdown in it")
            _check_cards(card.get("cards") or [], f"{here}.cards", depth, in_column=True)
        elif kind == "board":
            if not isinstance(card["board"], str) or not card["board"].strip():
                raise TemplateError(f"{here}: a board needs a title")
            if re.search(r"\*\S", card["board"]):
                raise TemplateError(f"{here}: a board title is plain text; the board doesn't render markdown in it")
            if depth + 1 > MAX_DEPTH:
                raise TemplateError(f"{here}: boards nest at most {MAX_DEPTH} deep in a template")
            _check_cards(card.get("cards") or [], f"{here}.cards", depth + 1)


def parse(path: Path, category: str) -> Template:
    where = f"{path.parent.name}/{path.name}"
    try:
        raw = yaml.safe_load(path.read_text())
    except yaml.YAMLError as e:
        raise TemplateError(f"{where}: not valid YAML ({e})") from None
    if not isinstance(raw, dict):
        raise TemplateError(f"{where}: a template is a mapping (name, use_when, cards)")
    extra = set(raw) - TEMPLATE_KEYS
    if extra:
        raise TemplateError(f"{where}: unknown keys {', '.join(sorted(extra))} (allowed: {', '.join(sorted(TEMPLATE_KEYS))})")
    for key in ("name", "use_when"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            raise TemplateError(f"{where}: {key} is required")
    if not raw.get("cards"):
        raise TemplateError(f"{where}: cards is required")
    _check_cards(raw["cards"], f"{where} cards")
    also = raw.get("also") or []
    if not isinstance(also, list) or not all(isinstance(a, str) for a in also):
        raise TemplateError(f"{where}: also is a list of category slugs")
    theme = raw.get("theme")
    if theme is not None and (theme not in themes.PRESETS or theme == "vault"):
        raise TemplateError(f"{where}: theme is one of {', '.join(p for p in themes.PRESETS if p != 'vault')}")
    source = raw.get("source")
    if source is not None and not (isinstance(source, str) and source.startswith("https://")):
        raise TemplateError(f"{where}: source is an https URL")
    return Template(
        slug=path.stem,
        category=category,
        name=raw["name"].strip(),
        use_when=" ".join(raw["use_when"].split()),
        cards=raw["cards"],
        also=tuple(dict.fromkeys(also)),
        source=source,
        theme=theme,
        path=path,
    )


def load(root: Path = ROOT, strict: bool = True) -> Catalog:
    """Read and check the whole library. Strict (the tests): raise TemplateError on the first
    problem. Lenient (the app): leave a bad file out and list it in ``problems``, so one typo in a
    template being edited doesn't take the rest of the library with it."""
    catalog = Catalog()
    index = root / "categories.yaml"
    if not index.is_file():
        return catalog
    cats = yaml.safe_load(index.read_text()) or []
    known: set[str] = set()
    for i, c in enumerate(cats):
        if not isinstance(c, dict) or not SLUG.fullmatch(str(c.get("slug", ""))) or not c.get("name"):
            raise TemplateError(f"categories.yaml[{i}]: each category has a slug and a name")
        if c["slug"] in known:
            raise TemplateError(f"categories.yaml: {c['slug']} is listed twice")
        known.add(c["slug"])
        catalog.categories.append({"slug": c["slug"], "name": c["name"], "blurb": c.get("blurb", ""), "source": c.get("source")})
    names: dict[str, str] = {}
    sources: dict[str, str] = {}
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        if folder.name not in known:
            raise TemplateError(f"{folder.name}/: not a category in categories.yaml")
        for path in sorted(folder.glob("*.yaml")):
            try:
                t = _admit(path, folder.name, catalog, known, names, sources)
            except TemplateError as e:
                if strict:
                    raise
                catalog.problems.append(str(e))
                continue
            catalog.templates[t.slug] = t
            names[t.name.lower()] = f"{folder.name}/{path.name}"
            if t.source:
                sources[t.source.rstrip("/").lower()] = f"{folder.name}/{path.name}"
    return catalog


def _admit(path: Path, category: str, catalog: Catalog, known: set[str], names: dict, sources: dict) -> Template:
    """One file, checked on its own and against the templates already admitted."""
    folder = path.parent
    if not SLUG.fullmatch(path.stem):
        raise TemplateError(f"{folder.name}/{path.name}: file names are lowercase-with-dashes")
    t = parse(path, category)
    where = f"{folder.name}/{path.name}"
    if t.slug in catalog.templates:
        raise TemplateError(f"{where}: {t.slug} is already {catalog.templates[t.slug].category}/{t.slug}.yaml")
    if t.name.lower() in names:
        raise TemplateError(f"{where}: the name {t.name!r} is already used by {names[t.name.lower()]}")
    if t.source and t.source.rstrip("/").lower() in sources:
        raise TemplateError(f"{where}: {t.source} is already the source of {sources[t.source.rstrip('/').lower()]}")
    for a in t.also:
        if a not in known or a == t.category:
            raise TemplateError(f"{where}: also lists {a!r}, which isn't another category")
    return t


_cache: dict[Path, tuple[tuple, Catalog]] = {}


def catalog(root: Path = ROOT) -> Catalog:
    """The library, re-read whenever a file in it changes (edit a template, use it at once)."""
    files = sorted(root.rglob("*.yaml")) if root.is_dir() else []
    signature = tuple((str(p), p.stat().st_mtime_ns) for p in files)
    hit = _cache.get(root)
    if hit and hit[0] == signature:
        return hit[1]
    fresh = load(root, strict=False)
    _cache[root] = (signature, fresh)
    return fresh


# ---------------------------------------------------------------- layout

def count_cards(cards: list[Any]) -> int:
    n = 0
    for card in cards:
        if card == "break":
            continue
        n += 1
        if "column" in card:
            n += len(card.get("cards") or [])
    return n


def _item(card: dict[str, Any]) -> dict[str, Any]:
    """A card spec for Store.build_board, before placement."""
    color = COLORS.get(card.get("color") or "")
    if "note" in card:
        return {"kind": "note", "text": card["note"].strip(), "data": {}, "color": color, "w": card.get("width")}
    if "todo" in card:
        items = [i if isinstance(i, dict) else {"text": i} for i in card["items"]]
        return {"kind": "todo", "text": card["todo"].strip(), "data": {"items": items}, "color": color, "w": card.get("width")}
    if "swatch" in card:
        return {"kind": "swatch", "text": card.get("text", ""), "data": {"hex": card["swatch"]}, "color": None, "w": None}
    if "column" in card:
        return {
            "kind": "column", "text": card["column"].strip(), "data": {}, "color": color, "w": card.get("width"),
            "children": [_item(c) for c in card.get("cards") or []],
        }
    return {
        "kind": "board", "text": "", "data": {}, "color": color, "w": None,
        "board": {"title": card["board"].strip(), "folder": bool(card.get("folder")), "cards": plan(card.get("cards") or [])},
    }


def _size(item: dict[str, Any]) -> tuple[float, float]:
    w = float(item["w"] or layout.DEFAULT_WIDTH[item["kind"]])
    if item["kind"] == "column":
        inner = w - 2 * layout.COLUMN_PAD
        return w, layout.column_height([layout.estimate_height(c["kind"], c["text"], c["data"], inner) for c in item["children"]])
    return w, layout.estimate_height(item["kind"], item["text"], item["data"], w)


def plan(cards: list[Any]) -> list[dict[str, Any]]:
    """Template cards → placed card specs (x, y, w), in rows. Columns carry their children and
    boards their own plan; Store.build_board writes them."""
    items: list[dict[str, Any] | None] = [None if c == "break" else _item(c) for c in cards]
    sizes = [None if i is None else _size(i) for i in items]
    placed = [i for i in items if i is not None]
    for item, (x, y), size in zip(placed, layout.flow(sizes), (s for s in sizes if s is not None)):
        item.update(x=x, y=y, w=size[0], h=size[1])
    return placed


def preview(t: Template) -> list[dict[str, Any]]:
    """The top level of a template as boxes, for the New board dialog's thumbnails."""
    out = []
    for item in plan(t.cards):
        title = item["board"]["title"] if item["kind"] == "board" else item["text"].split("\n")[0].lstrip("# ").strip()
        out.append({
            "kind": item["kind"], "title": title[:60], "color": item["color"],
            "x": round(item["x"]), "y": round(item["y"]), "w": round(item["w"]), "h": round(item["h"]),
            "children": len(item.get("children") or []),
        })
    return out


# ---------------------------------------------------------------- search

def _text(cards: list[Any]) -> str:
    parts = []
    for card in cards:
        if card == "break":
            continue
        for key in ("note", "todo", "column", "board", "text"):
            if isinstance(card.get(key), str):
                parts.append(card[key])
        for item in card.get("items") or []:
            parts.append(item["text"] if isinstance(item, dict) else item)
        parts.append(_text(card.get("cards") or []))
    return " ".join(parts)


STOP = {"a", "an", "and", "the", "for", "of", "to", "my", "our", "in", "on", "with", "me", "board", "template", "plan"}


def search(cat: Catalog, query: str = "", category: str = "", limit: int | None = None) -> list[Template]:
    """Templates matching every word of ``query`` (name and use first, then contents), optionally
    only those in ``category``. No query: the category's templates (or all) by name."""
    pool = cat.in_category(category) if category else list(cat.templates.values())
    words = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) > 1 and w not in STOP]
    # "mood board" finds "moodboard", "work flow" finds "workflow": a pair also counts as one word.
    pairs = {i: words[i] + words[i + 1] for i in range(len(words) - 1)}
    if not words:
        found = sorted(pool, key=lambda t: t.name.lower())
        return found[:limit] if limit else found
    names = {c["slug"]: c["name"].lower() for c in cat.categories}
    scored = []
    for t in pool:
        head = f"{t.name} {t.slug}".lower()
        use = t.use_when.lower()
        cats = " ".join([t.category, names.get(t.category, ""), *t.also, *(names.get(a, "") for a in t.also)]).lower()
        body = _text(t.cards).lower()
        def weight(w: str) -> int:
            return 6 * (w in head) + 3 * (w in use) + 2 * (w in cats) + (w in body)

        score, i = 0, 0
        while i < len(words):
            joined = weight(pairs[i]) if i in pairs else 0
            if joined:
                score, i = score + 2 * joined, i + 2
                continue
            single = weight(words[i])
            if not single:
                break
            score, i = score + single, i + 1
        else:
            scored.append((score, t))
    scored.sort(key=lambda st: (-st[0], st[1].name.lower()))
    found = [t for _, t in scored]
    return found[:limit] if limit else found
