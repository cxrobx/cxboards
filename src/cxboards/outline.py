"""A board as text, in reading order: what an agent reads before it edits."""

from __future__ import annotations

from typing import Any

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
    elif kind == "audio":
        body = f"{data.get('name')} ({data.get('path')})" + (f" — {_one_line(card['text'], 100)}" if card["text"] else "")
    elif kind == "board":
        child = card.get("board") or {}
        body = f"→ {child.get('title', '?')} ({child.get('id', data.get('board_id'))}, {child.get('card_count', 0)} cards)"
    else:
        body = _one_line(card["text"])
    by = " ·agent" if card.get("updated_by") == "agent" else ""
    return f"[{kind} {cid}{by}] {body}"


def board_outline(store: Store, board_id: str, base_url: str) -> str:
    state = store.board_state(board_id)
    board = state["board"]
    trail = " / ".join(b["title"] for b in state["breadcrumbs"])
    lines = [
        f"# {board['title']}  ({board['id']}, rev {board['rev']})",
        f"path: {trail}" if len(state["breadcrumbs"]) > 1 else "",
        board["description"] or "",
        f"live: {base_url}/b/{board['id']}",
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
    return "\n".join(line for line in lines if line is not None).replace("\n\n\n", "\n\n")
