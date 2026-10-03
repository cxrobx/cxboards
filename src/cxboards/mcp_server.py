"""The ``cxboards`` MCP: a thin stdio client of the local CXBoards API.

Every write goes through the same HTTP API the UI uses, tagged
``X-CXBoards-Actor: agent``, so Chris sees each change land live on the open
board with the touched cards highlighted. The server must be running
(LaunchAgent ``com.cx.cxboards.server``); if it isn't, tools say so.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import quote

import httpx
from mcp.server.fastmcp import FastMCP

from .config import load_config

INSTRUCTIONS = """CXBoards is Chris's visual planning board (Milanote-shaped): boards hold cards
(note, todo, link, image, audio, column, board). He plans creative sessions on it and
watches it live while you edit, so work in small, readable moves.

- read_board before you change a board; it lists every card id in reading order.
- Never think in coordinates. Place cards with `column` (id or title) or `near` (a card
  id), or leave both out and the board finds the next free spot in reading order.
- Group related cards into a column (group_into_column), and move a big topic onto its
  own nested board (make_sub_board) rather than sprawling.
- Audio cards point at files on disk (bounces in /Volumes/ChrisX/MuZik/...); CXBoards
  only reads them. Never copy or move his music files.
- Boards are snapshotted into Onyx under Artifacts/Muzik/Boards automatically."""

mcp = FastMCP("cxboards", instructions=INSTRUCTIONS)

_client: httpx.Client | None = None


def set_client(client: httpx.Client) -> None:
    """Tests inject a client bound to the app; production builds one lazily."""
    global _client
    _client = client


def _http() -> httpx.Client:
    global _client
    if _client is None:
        config = load_config()
        _client = httpx.Client(base_url=config.base_url, timeout=30)
    return _client


HEADERS = {"X-CXBoards": "1", "X-CXBoards-Actor": "agent"}


def _call(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    try:
        resp = _http().request(method, path, json=body, headers=HEADERS)
    except httpx.ConnectError as exc:
        raise ValueError(
            "CXBoards isn't running. Start it with `launchctl kickstart -k gui/$(id -u)/com.cx.cxboards.server` "
            "or `cd ~/Projects/cxboards && .venv/bin/cxboards serve`."
        ) from exc
    if resp.status_code >= 400:
        try:
            message = resp.json().get("error") or resp.text
        except ValueError:
            message = resp.text
        raise ValueError(f"CXBoards said: {message}")
    if resp.headers.get("content-type", "").startswith("application/json"):
        return resp.json()
    return resp.text


def _base() -> str:
    return str(_http().base_url).rstrip("/")


def _brief(card: dict[str, Any]) -> str:
    label = card["text"] or card["data"].get("title") or card["data"].get("name") or card["data"].get("url") or ""
    label = " ".join(label.split())[:60]
    where = f" in column {card['column_id']}" if card.get("column_id") else ""
    return f"{card['kind']} {card['id']}{where}" + (f": {label}" if label else "")


@mcp.tool()
def list_boards() -> str:
    """Every board: title, id, card count, and which board it's nested in."""
    boards = _call("GET", "/api/boards")
    if not boards:
        return "No boards yet. create_board makes one."
    titles = {b["id"]: b["title"] for b in boards}
    lines = []
    for b in boards:
        parent = f" · inside {titles.get(b['parent_id'], b['parent_id'])}" if b["parent_id"] else ""
        template = " · TEMPLATE" if b.get("is_template") else ""
        lines.append(f"- {b['title']} ({b['id']}) · {b['card_count']} cards{parent}{template} · updated {b['updated_at']}")
    return "\n".join(lines)


@mcp.tool()
def read_board(board: str) -> str:
    """A board in reading order with every card id. `board` is an id or a title (a unique fragment works)."""
    return _call("GET", f"/api/boards/{board}/outline")


@mcp.tool()
def create_board(title: str, description: str = "", parent: str = "", template: str = "") -> str:
    """Make a board. With `parent` (id or title) it is nested there and a board card appears on the parent.
    With `template` (a template board's id or title, see list_boards), it starts as a copy of that template."""
    board = _call(
        "POST", "/api/boards",
        {"title": title, "description": description, "parent": parent or None, "template": template or None},
    )
    return f"Created {board['title']} ({board['id']}). Live: {_base()}/b/{board['id']}"


@mcp.tool()
def add_cards(
    board: str,
    cards: list[dict[str, Any]],
    column: str = "",
    near: str = "",
    side: str = "right",
    unsorted: bool = False,
) -> str:
    """Add one or more cards in a single step (one live update, one undo step for Chris).

    Each card is a dict with `kind` plus:
      note   {text}                         markdown
      todo   {title?, items: [str | {text, done, indent}]}
      link   {url, text?}                   preview (title, image, player) fills in by itself
      image  {path | url, text?}            text = caption; the image is copied into CXBoards
      media  {path, text?}                  any file on disk: becomes an audio, video or file card;
                                            only ever read (a .flp can then be opened in FL)
      swatch {hex, text?}                   a colour swatch
      column {title, cards?: [...]}         a column, optionally with its own cards
      color  optional on any card: a CSS colour for its accent stripe
    Placement (applies to the whole call): `column` puts every card into that column (id or
    title); `near` puts the first card beside that card id (side right|below) and each next
    card beside the one before; `unsorted` drops them in the board's Unsorted tray for Chris
    to place; none of these = next free spots in reading order.
    """
    specs = []
    for card in cards:
        spec = dict(card)
        if column and spec.get("kind") != "column":
            spec["column"] = column
        if unsorted:
            spec["unsorted"] = True
        specs.append(spec)
    if near and specs:
        specs[0]["near"] = near
        specs[0]["side"] = side
    created = _call("POST", f"/api/boards/{board}/cards/batch", {"cards": specs})
    return "Added:\n" + "\n".join(f"- {_brief(c)}" for c in created)


@mcp.tool()
def update_card(
    card_id: str,
    text: str | None = None,
    items: list[Any] | None = None,
    url: str | None = None,
    color: str | None = None,
) -> str:
    """Change a card. `text` is a note's body, a todo's or column's title, or a caption/comment.
    `items` replaces a todo's whole list ([str | {text, done}]) — read it first to keep ticks."""
    body: dict[str, Any] = {}
    if text is not None:
        body["text"] = text
    if items is not None:
        body["items"] = items
    if url is not None:
        body["url"] = url
    if color is not None:
        body["color"] = color
    if not body:
        raise ValueError("nothing to change")
    return "Updated " + _brief(_call("PATCH", f"/api/cards/{card_id}", body))


@mcp.tool()
def move_card(
    card_id: str,
    column: str = "",
    index: int | None = None,
    near: str = "",
    side: str = "right",
    out_of_column: bool = False,
    board: str = "",
    unsorted: bool = False,
) -> str:
    """Move a card: into a `column` (id or title, optional `index` within it), out of its column
    (`out_of_column`), beside another card (`near`), into the Unsorted tray (`unsorted`), or onto
    another `board` (a column brings its cards). Locked cards refuse."""
    body: dict[str, Any] = {"side": side}
    if board:
        body["board"] = board
    elif unsorted:
        body["unsorted"] = True
    elif out_of_column:
        body["column"] = ""
        if near:
            body["near"] = near
    elif column:
        body["column"] = column
        if index is not None:
            body["index"] = index
    elif near:
        body["near"] = near
    else:
        raise ValueError("say where: column, near, out_of_column, unsorted or board")
    return "Moved " + _brief(_call("POST", f"/api/cards/{card_id}/move", body))


@mcp.tool()
def delete_card(card_id: str) -> str:
    """Move a card to the trash (Chris can restore it). A column's cards go back onto the canvas;
    a board card's board becomes top-level. Locked cards refuse."""
    _call("DELETE", f"/api/cards/{card_id}")
    return f"Moved {card_id} to the trash."


@mcp.tool()
def duplicate_cards(card_ids: list[str], board: str = "") -> str:
    """Copy cards (a column brings its cards, a board card copies its whole board). Without `board`
    the copies land beside the originals; with it, in the next free spot on that board."""
    copies = _call("POST", "/api/cards/duplicate", {"card_ids": card_ids, "board": board or None})
    return "Copied:\n" + "\n".join(f"- {_brief(c)}" for c in copies)


@mcp.tool()
def search(query: str) -> str:
    """Search every board's cards and titles. `label:name words` narrows to one label."""
    results = _call("GET", f"/api/search?q={quote(query)}")
    if not results:
        return f"Nothing matches {query!r}."
    lines = []
    for r in results:
        if r["type"] == "board":
            lines.append(f"- board {r['board_id']}: {r['title']}")
        else:
            lines.append(f"- {r['kind']} {r['card_id']} on {r['board_title']} ({r['board_id']}): {r['title']}")
    return "\n".join(lines)


@mcp.tool()
def connect_cards(from_card: str, to_card: str, label: str = "", arrow: str = "end", remove: bool = False) -> str:
    """Draw a line between two cards on the same board (arrow: end | both | none), optionally labelled.
    With `remove`, take the line between them away instead."""
    if remove:
        board_id = _call("GET", f"/api/cards/{from_card}/board")["board_id"]
        for line in _call("GET", f"/api/boards/{board_id}")["connectors"]:
            if {line["from_id"], line["to_id"]} == {from_card, to_card}:
                _call("DELETE", f"/api/connectors/{line['id']}")
                return f"Removed the line {line['id']}."
        raise ValueError("those cards aren't connected")
    line = _call("POST", "/api/connectors", {"from": from_card, "to": to_card, "label": label, "arrow": arrow})
    return f"Connected {from_card} → {to_card} ({line['id']})" + (f": {label}" if label else "")


@mcp.tool()
def label_cards(card_ids: list[str], labels: list[str], remove: bool = False) -> str:
    """Put labels on cards (created if new, e.g. "idea", "for Beth", "done"), or take them off with `remove`.
    `search("label:idea")` then finds them across every board."""
    result = _call("POST", "/api/cards/labels", {"card_ids": card_ids, "names": labels, "remove": remove})
    lines = [f"- {r['card_id']}: {', '.join(lb['name'] for lb in r['labels']) or '(no labels)'}" for r in result]
    return "Labels now:\n" + "\n".join(lines)


@mcp.tool()
def set_board_theme(
    board: str,
    preset: str = "",
    ground: str = "",
    ink: str = "",
    accent: str = "",
    font: str = "mono",
    corners: str = "round",
) -> str:
    """Theme a board (the whole app takes it on while the board is open, and its Onyx page too).
    Either a `preset`: vault (the default look), chrisx, film, studio, paper, midnight, sage, rose;
    or custom hex colours `ground` (background), `ink` (text), `accent`, with `font` mono|sans|serif|chrisx
    and `corners` round|square. Unreadable custom colours are corrected, not refused."""
    if preset:
        theme: Any = preset
    elif ground and ink:
        theme = {"preset": "custom", "ground": ground, "ink": ink, "accent": accent or ink, "font": font, "corners": corners}
    else:
        raise ValueError("give a preset, or ground and ink colours")
    result = _call("PATCH", f"/api/boards/{board}", {"theme": theme})
    picked = result.get("theme") or {"preset": "vault"}
    return f"{result['title']} now uses the {picked.get('preset')} theme."


@mcp.tool()
def arrange(board: str, mode: str = "grid", card_ids: list[str] | None = None) -> str:
    """Tidy canvas cards (all of them, or `card_ids`) into a `grid`, a `row`, or a `stack`, in reading order."""
    result = _call("POST", f"/api/boards/{board}/arrange", {"mode": mode, "card_ids": card_ids or []})
    return f"Arranged {len(result['arranged'])} cards as a {mode}."


@mcp.tool()
def group_into_column(board: str, card_ids: list[str], title: str) -> str:
    """Put cards into a new column titled `title`, in reading order, where the first of them was."""
    column = _call("POST", f"/api/boards/{board}/group", {"card_ids": card_ids, "title": title})
    return f"Grouped {len(card_ids)} cards into column {column['id']} ({title})."


@mcp.tool()
def make_sub_board(board: str, card_ids: list[str], title: str) -> str:
    """Move cards onto a new board nested in this one; a board card takes their place."""
    card = _call("POST", f"/api/boards/{board}/sub-board", {"card_ids": card_ids, "title": title})
    child = card["data"]["board_id"]
    return f"Made board {title} ({child}) from {len(card_ids)} cards. Live: {_base()}/b/{child}"


@mcp.tool()
def export_board(board: str, format: str = "snapshot") -> str:
    """Export a board. `snapshot`: write its Onyx page now (it also happens by itself after each change).
    `markdown`: return the board as Markdown. `vault`: save it as a note in the Obsidian vault's
    Inbox/Quick Notes (images to Other/Attachments; a note Chris has edited is never overwritten)."""
    if format == "markdown":
        return _call("GET", f"/api/boards/{board}/export.md")
    if format == "vault":
        result = _call("POST", f"/api/boards/{board}/export/vault")
        return f"Saved to the vault: {result['relative']}"
    if format != "snapshot":
        raise ValueError("format is snapshot, markdown or vault")
    result = _call("POST", f"/api/boards/{board}/export")
    return f"Snapshot written: Artifacts/{result['artifacts']} ({result['path']})"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
