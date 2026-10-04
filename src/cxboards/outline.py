"""A board as text, in reading order: what an agent reads before it edits."""

from __future__ import annotations

from typing import Any

from . import themes
from .store import Store


def _one_line(text: str, limit: int = 160) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def card_line(card: dict[str, Any]) -> str:
    kind, cid, data = card["kind"], card["id"], card["data"]
    if kind == "note":
        body = _one_line(card["text"]) or "(empty)"
    elif kind == "todo":
        items = " ".join(f"[{'x' if i['done'] else ' '}] {i['text']}" for i in data.get("items", []))
        body = _one_line(f"{card['text']}: {items}" if card["text"] else items) or "(empty)"
    elif kind == "link":
        title = data.get("title") or data.get("url")
        body = f"{title} <{data.get('url')}>" + (f" — {_one_line(card['text'], 100)}" if card["text"] else "")
    elif kind == "image":
        body = f"{data.get('file')}" + (f" — {_one_line(card['text'], 100)}" if card["text"] else "")
    elif kind in ("audio", "video", "file"):
        copied = " [copied]" if data.get("copied") else ""
        body = f"{data.get('name')} ({data.get('path')}){copied}" + (f" — {_one_line(card['text'], 100)}" if card["text"] else "")
    elif kind == "swatch":
        body = data.get("hex", "") + (f" — {_one_line(card['text'], 100)}" if card["text"] else "")
    elif kind == "animation":
        motion = data.get("motion") or {}
        body = f"{_one_line(card['text'], 100) or 'untitled'} ({motion.get('loop', 6):g}s loop)"
    elif kind == "sketch":
        body = f"sketch, {len(data.get('paths', []))} strokes" + (f" — {_one_line(card['text'], 100)}" if card["text"] else "")
    elif kind == "board":
        child = card.get("board") or {}
        body = f"→ {child.get('title', '?')} ({child.get('id', data.get('board_id'))}, {child.get('card_count', 0)} cards)"
    else:
        body = _one_line(card["text"])
    motion = data.get("motion")
    if kind == "image" and motion:
        body += f" ·animated ({motion.get('loop', 6):g}s loop)"
    if motion and motion.get("error"):
        body += f" ·ANIMATION ERROR: {motion['error']}"
    by = " ·agent" if card.get("updated_by") == "agent" else ""
    by += " ·locked" if card.get("locked") else ""
    return f"[{kind} {cid}{by}] {body}"


def board_outline(store: Store, board_id: str, base_url: str) -> str:
    state = store.board_state(board_id)
    board = state["board"]
    trail = " / ".join(b["title"] for b in state["breadcrumbs"])
    lines = [
        f"# {board['title']}  ({board['id']}, rev {board['rev']})",
        f"path: {trail}" if len(state["breadcrumbs"]) > 1 else "",
        board["description"] or "",
        f"live: {base_url}/b/{board['id']} · theme: {themes.label(board.get('theme'))}",
        "",
    ]
    order = store.reading_order(board_id)
    if not order:
        lines.append("(empty board)")
    for card in order:
        if card["kind"] == "column":
            lines.append(f"## column {card['id']}: {card['text'] or '(untitled)'}")
            for child in card.get("children", []):
                lines.append(f"  - {card_line(child)}")
            if not card.get("children"):
                lines.append("  (empty column)")
        else:
            lines.append(f"- {card_line(card)}")
    tray = [c for c in state["cards"] if c["tray"]]
    if tray:
        lines.append("## Unsorted (waiting to be placed)")
        lines.extend(f"  - {card_line(c)}" for c in tray)
    lines.extend(_lines_section(state))
    return "\n".join(line for line in lines if line is not None).replace("\n\n\n", "\n\n")


def _lines_section(state: dict[str, Any]) -> list[str]:
    connectors = state.get("connectors") or []
    if not connectors:
        return []
    out = ["## Lines"]
    for c in connectors:
        label = f": {c['label']}" if c.get("label") else ""
        out.append(f"  - {c['id']}  {c['from_id']} → {c['to_id']}{label}")
    return out
