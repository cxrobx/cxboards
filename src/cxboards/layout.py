"""Placement and arrangement: the only place card coordinates are decided.

Agents never send x/y. They say *where* in board terms (in a column, next to a
card, or nowhere in particular) and these functions turn that into a spot that
does not overlap anything. The UI reports each card's measured height back, so
the rectangles here track what is actually on screen; until it does, heights
are estimated from the content.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

GAP = 24
ORIGIN = (80.0, 80.0)
MAX_ROW_WIDTH = 1800.0
ROW_BAND = 120.0
COLUMN_HEADER = 56.0
COLUMN_PAD = 12.0
COLUMN_CHILD_GAP = 8.0

DEFAULT_WIDTH = {
    "note": 260.0,
    "todo": 260.0,
    "link": 300.0,
    "image": 300.0,
    "audio": 300.0,
    "column": 300.0,
    "board": 220.0,
}


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    h: float

    def overlaps(self, other: "Rect", gap: float = GAP / 2) -> bool:
        return not (
            self.x + self.w + gap <= other.x
            or other.x + other.w + gap <= self.x
            or self.y + self.h + gap <= other.y
            or other.y + other.h + gap <= self.y
        )


def estimate_height(kind: str, text: str, data: dict, width: float) -> float:
    """A first guess at a card's rendered height, replaced once the UI measures it."""
    chars_per_line = max(10, int((width - 28) / 7.8))
    if kind == "note":
        lines = sum(max(1, math.ceil(len(line) / chars_per_line)) for line in (text or " ").split("\n"))
        return 32 + 21 * lines
    if kind == "todo":
        items = data.get("items") or []
        return 44 + (28 if text else 0) + 28 * max(1, len(items))
    if kind == "link":
        return 250.0 if data.get("image") else 120.0
    if kind == "image":
        return 230.0 + (24 if text else 0)
    if kind == "audio":
        return 104.0 + (21 if text else 0)
    if kind == "board":
        return 120.0
    return 120.0


def column_height(child_heights: list[float]) -> float:
    inner = sum(h + COLUMN_CHILD_GAP for h in child_heights)
    return max(120.0, COLUMN_HEADER + inner + COLUMN_PAD)


def free_slot(existing: list[Rect], w: float, h: float) -> tuple[float, float]:
    """The first free spot in reading order (top row first, left to right)."""
    if not existing:
        return ORIGIN
    left = min(r.x for r in existing)
    top = min(r.y for r in existing)
    bottom = max(r.y + r.h for r in existing)
    candidates = {(left, top)}
    for r in existing:
        candidates.add((r.x + r.w + GAP, r.y))
        candidates.add((r.x, r.y + r.h + GAP))
    candidates.add((left, bottom + GAP))
    best: tuple[float, float] | None = None
    for x, y in candidates:
        if x + w > left + MAX_ROW_WIDTH and (x, y) != (left, bottom + GAP):
            continue
        spot = Rect(x, y, w, h)
        if any(spot.overlaps(r) for r in existing):
            continue
        if best is None or (y, x) < (best[1], best[0]):
            best = (x, y)
    return best if best is not None else (left, bottom + GAP)


def beside(anchor: Rect, existing: list[Rect], w: float, h: float, side: str = "right") -> tuple[float, float]:
    """Next to ``anchor``; slides down (or right, for ``below``) until clear."""
    if side == "below":
        x, y = anchor.x, anchor.y + anchor.h + GAP
        step = (GAP, 0.0)
    else:
        x, y = anchor.x + anchor.w + GAP, anchor.y
        step = (0.0, GAP)
    for _ in range(400):
        spot = Rect(x, y, w, h)
        if not any(spot.overlaps(r) for r in existing):
            return x, y
        x, y = x + step[0], y + step[1]
    return free_slot(existing, w, h)


def reading_order(rects: dict[str, Rect]) -> list[str]:
    """Ids sorted top-to-bottom in bands, then left-to-right."""
    return sorted(rects, key=lambda cid: (round(rects[cid].y / ROW_BAND), rects[cid].x, rects[cid].y))


def arrange(rects: list[tuple[str, Rect]], mode: str, origin: tuple[float, float]) -> dict[str, tuple[float, float]]:
    """New positions for ``rects`` (already in the order they should read)."""
    if not rects:
        return {}
    ox, oy = origin
    out: dict[str, tuple[float, float]] = {}
    if mode == "row":
        x = ox
        for cid, r in rects:
            out[cid] = (x, oy)
            x += r.w + GAP
        return out
    if mode == "stack":
        y = oy
        for cid, r in rects:
            out[cid] = (ox, y)
            y += r.h + GAP
        return out
    # grid: near-square, at most five across
    per_row = min(5, max(1, math.ceil(math.sqrt(len(rects)))))
    col_width = max(r.w for _, r in rects) + GAP
    y = oy
    for start in range(0, len(rects), per_row):
        row = rects[start : start + per_row]
        for i, (cid, _) in enumerate(row):
            out[cid] = (ox + i * col_width, y)
        y += max(r.h for _, r in row) + GAP
    return out
