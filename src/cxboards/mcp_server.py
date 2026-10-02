"""The ``cxboards`` MCP: a thin stdio client of the local CXBoards API.

Every write goes through the same HTTP API the UI uses, tagged
``X-CXBoards-Actor: agent``, so Chris sees each change land live on the open
board with the touched cards highlighted. The server must be running
(LaunchAgent ``com.cx.cxboards.server``); if it isn't, tools say so.
"""

from __future__ import annotations

import json
from typing import Any

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
        lines.append(f"- {b['title']} ({b['id']}) · {b['card_count']} cards{parent} · updated {b['updated_at']}")
    return "\n".join(lines)


@mcp.tool()
def read_board(board: str) -> str:
    """A board in reading order with every card id. `board` is an id or a title (a unique fragment works)."""
    return _call("GET", f"/api/boards/{board}/outline")


@mcp.tool()
def create_board(title: str, description: str = "", parent: str = "") -> str:
    """Make a board. With `parent` (id or title) it is nested there and a board card appears on the parent."""
    board = _call("POST", "/api/boards", {"title": title, "description": description, "parent": parent or None})
    return f"Created {board['title']} ({board['id']}). Live: {_base()}/b/{board['id']}"


@mcp.tool()
def add_cards(board: str, cards: list[dict[str, Any]], column: str = "", near: str = "", side: str = "right") -> str:
    """Add one or more cards in a single step (one live update for Chris).

    Each card is a dict with `kind` plus:
      note   {text}                         markdown
      todo   {title?, items: [str | {text, done}]}
      link   {url, text?}                   preview (title, image) fills in by itself
      image  {path | url, text?}            text = caption; the image is copied into CXBoards
      audio  {path, text?}                  absolute path to an audio file; only ever read
      column {title, cards?: [...]}         a column, optionally with its own cards
      color  optional on any card: a CSS colour for its accent stripe
    Placement (applies to the whole call): `column` puts every card into that column (id or
    title); `near` puts the first card beside that card id (side right|below) and each next
    card beside the one before; neither = next free spots in reading order.
    """
    specs = []
    for card in cards:
        spec = dict(card)
        if column and spec.get("kind") != "column":
            spec["column"] = column
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
) -> str:
    """Move a card: into a `column` (id or title, optional `index` within it), out of its column
    (`out_of_column`), beside another card (`near`), or onto another `board` (a column brings its cards)."""
    body: dict[str, Any] = {"side": side}
    if board:
        body["board"] = board
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
        raise ValueError("say where: column, near, out_of_column or board")
    return "Moved " + _brief(_call("POST", f"/api/cards/{card_id}/move", body))


@mcp.tool()
def delete_card(card_id: str) -> str:
    """Remove a card. A column's cards go back onto the canvas; a board card's board becomes top-level."""
    _call("DELETE", f"/api/cards/{card_id}")
    return f"Deleted {card_id}."


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
def snapshot_board(board: str) -> str:
    """Write the board's Onyx snapshot now (it also happens on its own a moment after each change)."""
    result = _call("POST", f"/api/boards/{board}/export")
    return f"Snapshot written: Artifacts/{result['artifacts']} ({result['path']})"


def run() -> None:
    mcp.run()


if __name__ == "__main__":
    run()
