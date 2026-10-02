"""SQLite storage and every board operation.

The HTTP API (and through it the MCP) is a thin shell over this class. Each
mutating method runs in one transaction, bumps the board's ``rev`` and, after
commit, tells the listeners which cards changed and who changed them. That one
hook drives both the live UI (SSE) and the Onyx snapshots.

Invariants (tests/test_store.py checks them):
  * Agent placement never overlaps an existing card's rectangle.
  * Deleting a card never deletes other content: a column's cards return to
    the canvas, a board card's board becomes a top-level board.
  * Every write bumps the touched board's rev exactly once per transaction.
  * Nothing is written outside the CXBoards home; audio is only ever read.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import shutil
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from . import layout
from .config import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, MAX_IMAGE_BYTES, Config
from .layout import Rect

KINDS = ("note", "todo", "link", "image", "audio", "column", "board")
ACTORS = ("chris", "agent", "system")

SCHEMA = """
CREATE TABLE IF NOT EXISTS boards (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    parent_id   TEXT REFERENCES boards(id) ON DELETE SET NULL,
    rev         INTEGER NOT NULL DEFAULT 0,
    export_slug TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    id          TEXT PRIMARY KEY,
    board_id    TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,
    column_id   TEXT,
    position    REAL NOT NULL DEFAULT 0,
    x           REAL NOT NULL DEFAULT 0,
    y           REAL NOT NULL DEFAULT 0,
    w           REAL NOT NULL DEFAULT 260,
    h           REAL NOT NULL DEFAULT 120,
    z           INTEGER NOT NULL DEFAULT 0,
    text        TEXT NOT NULL DEFAULT '',
    data        TEXT NOT NULL DEFAULT '{}',
    color       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT 'chris'
);
CREATE INDEX IF NOT EXISTS cards_board ON cards(board_id);
CREATE INDEX IF NOT EXISTS cards_column ON cards(column_id);
"""

ChangeListener = Callable[[str, int, list[str], str], None]


class NotFound(Exception):
    pass


class Invalid(Exception):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(5)}"


def slugify(title: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")
    return slug[:60].strip("-") or "board"


class Store:
    def __init__(self, config: Config):
        config.ensure_dirs()
        self.config = config
        self._lock = threading.RLock()
        self._db = sqlite3.connect(config.db_path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript(SCHEMA)
        self.listeners: list[ChangeListener] = []
        self._pending: dict[str, tuple[set[str], str]] | None = None

    # ------------------------------------------------------------------ plumbing

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            outer = self._pending is None
            if outer:
                self._pending = {}
                self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
                if outer:
                    revs: dict[str, int] = {}
                    for board_id in self._pending:
                        self._db.execute(
                            "UPDATE boards SET rev = rev + 1, updated_at = ? WHERE id = ?", (_now(), board_id)
                        )
                        row = self._db.execute("SELECT rev FROM boards WHERE id = ?", (board_id,)).fetchone()
                        if row is not None:
                            revs[board_id] = row["rev"]
                    self._db.execute("COMMIT")
                    pending, self._pending = self._pending, None
                    for board_id, rev in revs.items():
                        ids, actor = pending[board_id]
                        for listener in list(self.listeners):
                            listener(board_id, rev, sorted(ids), actor)
            except BaseException:
                if outer:
                    self._db.execute("ROLLBACK")
                    self._pending = None
                raise

    def batch(self):
        """Group several writes into one transaction: one rev bump and one event per board."""
        return self._tx()

    def _touch(self, board_id: str, card_ids: list[str] | tuple[str, ...], actor: str) -> None:
        assert self._pending is not None, "_touch outside a transaction"
        ids, _ = self._pending.get(board_id, (set(), actor))
        ids.update(card_ids)
        self._pending[board_id] = (ids, actor)

    @staticmethod
    def _actor(actor: str) -> str:
        if actor not in ACTORS:
            raise Invalid(f"actor must be one of {', '.join(ACTORS)}")
        return actor

    # ------------------------------------------------------------------ boards

    def _board_row(self, board_id: str) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
        if row is None:
            raise NotFound(f"no board {board_id}")
        return row

    @staticmethod
    def _board_dict(row: sqlite3.Row, card_count: int | None = None) -> dict[str, Any]:
        out = {k: row[k] for k in row.keys()}
        if card_count is not None:
            out["card_count"] = card_count
        return out

    def board(self, board_id: str) -> dict[str, Any]:
        with self._lock:
            return self._board_dict(self._board_row(board_id))

    def list_boards(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT b.*, (SELECT COUNT(*) FROM cards c WHERE c.board_id = b.id) AS n "
                "FROM boards b ORDER BY b.updated_at DESC"
            ).fetchall()
            return [{**self._board_dict(r), "card_count": r["n"]} for r in rows]

    def resolve_board(self, ref: str) -> dict[str, Any]:
        """A board by id, exact title, or a title fragment that matches exactly one board."""
        ref = (ref or "").strip()
        if not ref:
            raise Invalid("name a board (id or title)")
        with self._lock:
            row = self._db.execute("SELECT * FROM boards WHERE id = ?", (ref,)).fetchone()
            if row is not None:
                return self._board_dict(row)
            rows = self._db.execute("SELECT * FROM boards WHERE lower(title) = lower(?)", (ref,)).fetchall()
            if len(rows) == 1:
                return self._board_dict(rows[0])
            if not rows:
                rows = self._db.execute(
                    "SELECT * FROM boards WHERE lower(title) LIKE '%' || lower(?) || '%'", (ref,)
                ).fetchall()
            if len(rows) == 1:
                return self._board_dict(rows[0])
            if not rows:
                raise NotFound(f"no board matches {ref!r}")
            names = ", ".join(f"{r['title']} ({r['id']})" for r in rows)
            raise Invalid(f"{ref!r} matches several boards: {names}")

    def breadcrumbs(self, board_id: str) -> list[dict[str, str]]:
        with self._lock:
            trail: list[dict[str, str]] = []
            seen: set[str] = set()
            current: str | None = board_id
            while current and current not in seen:
                seen.add(current)
                row = self._board_row(current)
                trail.append({"id": row["id"], "title": row["title"]})
                current = row["parent_id"]
            return list(reversed(trail))

    def create_board(
        self, title: str, description: str = "", parent_id: str | None = None, actor: str = "chris"
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise Invalid("a board needs a title")
        self._actor(actor)
        with self._tx() as db:
            board_id = _new_id("b")
            now = _now()
            if parent_id:
                self._board_row(parent_id)
            db.execute(
                "INSERT INTO boards (id, title, description, parent_id, export_slug, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (board_id, title, description or "", parent_id, self._unique_slug(title), now, now),
            )
            self._touch(board_id, [], actor)
            if parent_id:
                self._insert_card(parent_id, "board", text="", data={"board_id": board_id}, actor=actor)
            return self._board_dict(self._board_row(board_id))

    def _unique_slug(self, title: str, exclude: str | None = None) -> str:
        base = slugify(title)
        slug, n = base, 2
        while self._db.execute(
            "SELECT 1 FROM boards WHERE export_slug = ? AND id IS NOT ?", (slug, exclude)
        ).fetchone():
            slug, n = f"{base}-{n}", n + 1
        return slug

    def update_board(
        self, board_id: str, title: str | None = None, description: str | None = None, actor: str = "chris"
    ) -> dict[str, Any]:
        self._actor(actor)
        with self._tx() as db:
            row = self._board_row(board_id)
            if title is not None:
                title = title.strip()
                if not title:
                    raise Invalid("a board needs a title")
                db.execute(
                    "UPDATE boards SET title = ?, export_slug = ? WHERE id = ?",
                    (title, self._unique_slug(title, exclude=board_id), board_id),
                )
            if description is not None:
                db.execute("UPDATE boards SET description = ? WHERE id = ?", (description, board_id))
            self._touch(board_id, [], actor)
            if row["parent_id"]:
                self._touch(row["parent_id"], self._board_card_ids(board_id), actor)
            return self._board_dict(self._board_row(board_id))

    def _board_card_ids(self, child_id: str) -> list[str]:
        rows = self._db.execute(
            "SELECT id FROM cards WHERE kind = 'board' AND json_extract(data, '$.board_id') = ?", (child_id,)
        ).fetchall()
        return [r["id"] for r in rows]

    def _subtree(self, board_id: str) -> set[str]:
        """``board_id`` and every board nested under it."""
        found, queue = {board_id}, [board_id]
        while queue:
            kids = self._db.execute("SELECT id FROM boards WHERE parent_id = ?", (queue.pop(),)).fetchall()
            for kid in kids:
                if kid["id"] not in found:
                    found.add(kid["id"])
                    queue.append(kid["id"])
        return found

    def delete_board(self, board_id: str, actor: str = "chris") -> list[str]:
        """Delete a board and the boards nested in it. Returns the export slugs to remove."""
        self._actor(actor)
        with self._tx() as db:
            row = self._board_row(board_id)
            doomed = [board_id]
            i = 0
            while i < len(doomed):
                kids = db.execute("SELECT id FROM boards WHERE parent_id = ?", (doomed[i],)).fetchall()
                doomed.extend(k["id"] for k in kids)
                i += 1
            slugs = [
                r["export_slug"]
                for r in db.execute(
                    f"SELECT export_slug FROM boards WHERE id IN ({','.join('?' * len(doomed))})", doomed
                ).fetchall()
                if r["export_slug"]
            ]
            parent_cards = self._board_card_ids(board_id)
            for cid in parent_cards:
                db.execute("DELETE FROM cards WHERE id = ?", (cid,))
            for bid in reversed(doomed):
                db.execute("DELETE FROM cards WHERE board_id = ?", (bid,))
                db.execute("DELETE FROM boards WHERE id = ?", (bid,))
            if row["parent_id"]:
                self._touch(row["parent_id"], parent_cards, actor)
            return slugs

    # ------------------------------------------------------------------ cards: reads

    @staticmethod
    def _card_dict(row: sqlite3.Row) -> dict[str, Any]:
        out = {k: row[k] for k in row.keys()}
        out["data"] = json.loads(out["data"] or "{}")
        return out

    def _card_row(self, card_id: str) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
        if row is None:
            raise NotFound(f"no card {card_id}")
        return row

    def card(self, card_id: str) -> dict[str, Any]:
        with self._lock:
            return self._card_dict(self._card_row(card_id))

    def cards(self, board_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM cards WHERE board_id = ? ORDER BY z, created_at", (board_id,)
            ).fetchall()
            return [self._card_dict(r) for r in rows]

    def board_state(self, board_id: str) -> dict[str, Any]:
        with self._lock:
            board = self._board_dict(self._board_row(board_id))
            cards = self.cards(board_id)
            for card in cards:
                if card["kind"] == "board":
                    child_id = card["data"].get("board_id")
                    child = self._db.execute(
                        "SELECT b.title, (SELECT COUNT(*) FROM cards c WHERE c.board_id = b.id) AS n "
                        "FROM boards b WHERE b.id = ?",
                        (child_id,),
                    ).fetchone()
                    card["board"] = (
                        {"id": child_id, "title": child["title"], "card_count": child["n"]} if child else None
                    )
            return {
                "board": board,
                "cards": cards,
                "breadcrumbs": self.breadcrumbs(board_id),
            }

    def reading_order(self, board_id: str) -> list[dict[str, Any]]:
        """Canvas cards top-to-bottom, left-to-right; a column's cards follow it as ``children``."""
        cards = self.board_state(board_id)["cards"]
        by_id = {c["id"]: c for c in cards}
        canvas = {c["id"]: Rect(c["x"], c["y"], c["w"], c["h"]) for c in cards if not c["column_id"]}
        out = []
        for cid in layout.reading_order(canvas):
            card = dict(by_id[cid])
            if card["kind"] == "column":
                card["children"] = sorted(
                    (c for c in cards if c["column_id"] == cid), key=lambda c: c["position"]
                )
            out.append(card)
        return out

    # ------------------------------------------------------------------ cards: writes

    def _canvas_rects(self, board_id: str, exclude: set[str] | None = None) -> list[Rect]:
        rows = self._db.execute(
            "SELECT id, x, y, w, h FROM cards WHERE board_id = ? AND column_id IS NULL", (board_id,)
        ).fetchall()
        return [Rect(r["x"], r["y"], r["w"], r["h"]) for r in rows if not exclude or r["id"] not in exclude]

    def _normalize(self, kind: str, text: str, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data or {})
        if kind == "todo":
            items = data.get("items") or []
            norm = []
            for item in items:
                if isinstance(item, str):
                    norm.append({"text": item, "done": False})
                elif isinstance(item, dict) and str(item.get("text", "")).strip():
                    norm.append({"text": str(item["text"]), "done": bool(item.get("done"))})
            data["items"] = norm
        elif kind == "link":
            url = str(data.get("url", "")).strip()
            if not re.match(r"^https?://", url):
                raise Invalid("a link card needs an http(s) url")
            data["url"] = url
        elif kind == "image":
            name = str(data.get("file", ""))
            if not name or "/" in name or not (self.config.uploads_dir / name).is_file():
                raise Invalid("an image card needs an uploaded file")
        elif kind == "audio":
            path = Path(str(data.get("path", ""))).expanduser()
            if not path.is_absolute():
                raise Invalid("an audio card needs an absolute path")
            if path.suffix.lower() not in AUDIO_EXTENSIONS:
                raise Invalid(f"audio must be one of {', '.join(sorted(AUDIO_EXTENSIONS))}")
            if not path.is_file():
                raise Invalid(f"no audio file at {path}")
            data["path"] = str(path)
            data.setdefault("name", path.name)
        elif kind == "board":
            if not data.get("board_id"):
                raise Invalid("a board card needs a board_id")
        return data

    def _insert_card(
        self,
        board_id: str,
        kind: str,
        *,
        text: str = "",
        data: dict[str, Any] | None = None,
        color: str | None = None,
        column_id: str | None = None,
        index: int | None = None,
        near: str | None = None,
        side: str = "right",
        x: float | None = None,
        y: float | None = None,
        w: float | None = None,
        actor: str,
    ) -> str:
        if kind not in KINDS:
            raise Invalid(f"kind must be one of {', '.join(KINDS)}")
        self._board_row(board_id)
        data = self._normalize(kind, text, data or {})
        width = float(w) if w else layout.DEFAULT_WIDTH[kind]
        card_id = _new_id("c")
        now = _now()
        z = (self._db.execute("SELECT MAX(z) AS z FROM cards WHERE board_id = ?", (board_id,)).fetchone()["z"] or 0) + 1
        cx, cy, position = 0.0, 0.0, 0.0
        if column_id:
            column = self._column(column_id, board_id)
            if kind in ("column",):
                raise Invalid("a column can't go inside a column")
            width = column["w"] - 2 * layout.COLUMN_PAD
            position = self._slot_position(column_id, index)
            cx, cy = column["x"], column["y"]
        height = layout.estimate_height(kind, text, data, width)
        if not column_id:
            existing = self._canvas_rects(board_id)
            if x is not None and y is not None:
                cx, cy = float(x), float(y)
            elif near:
                anchor = self._card_row(near)
                if anchor["board_id"] != board_id:
                    raise Invalid(f"card {near} is on another board")
                if anchor["column_id"]:
                    anchor = self._card_row(anchor["column_id"])
                cx, cy = layout.beside(
                    Rect(anchor["x"], anchor["y"], anchor["w"], anchor["h"]), existing, width, height, side
                )
            else:
                cx, cy = layout.free_slot(existing, width, height)
        self._db.execute(
            "INSERT INTO cards (id, board_id, kind, column_id, position, x, y, w, h, z, text, data, color, "
            "created_at, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                card_id, board_id, kind, column_id, position, cx, cy, width, height, z,
                text or "", json.dumps(data), color, now, now, actor,
            ),
        )
        touched = [card_id]
        if column_id:
            self._refit_column(column_id)
            touched.append(column_id)
        self._touch(board_id, touched, actor)
        return card_id

    def _column(self, column_id: str, board_id: str) -> sqlite3.Row:
        column = self._card_row(column_id)
        if column["kind"] != "column":
            raise Invalid(f"{column_id} is not a column")
        if column["board_id"] != board_id:
            raise Invalid(f"column {column_id} is on another board")
        return column

    def _slot_position(self, column_id: str, index: int | None, exclude: str | None = None) -> float:
        rows = self._db.execute(
            "SELECT id, position FROM cards WHERE column_id = ? AND id IS NOT ? ORDER BY position",
            (column_id, exclude),
        ).fetchall()
        positions = [r["position"] for r in rows]
        if index is None or index >= len(positions):
            return (positions[-1] + 1.0) if positions else 1.0
        index = max(0, index)
        before = positions[index - 1] if index > 0 else positions[0] - 1.0
        return (before + positions[index]) / 2.0

    def _refit_column(self, column_id: str) -> None:
        rows = self._db.execute(
            "SELECT h FROM cards WHERE column_id = ? ORDER BY position", (column_id,)
        ).fetchall()
        self._db.execute(
            "UPDATE cards SET h = ? WHERE id = ?", (layout.column_height([r["h"] for r in rows]), column_id)
        )

    def add_card(self, board_id: str, kind: str, actor: str = "chris", **fields: Any) -> dict[str, Any]:
        self._actor(actor)
        with self._tx():
            card_id = self._insert_card(board_id, kind, actor=actor, **fields)
            return self._card_dict(self._card_row(card_id))

    def add_cards(self, board_id: str, specs: list[dict[str, Any]], actor: str = "agent") -> list[dict[str, Any]]:
        """Several cards in one transaction (one rev, one event). Each spec is add_card's fields plus ``kind``."""
        self._actor(actor)
        with self._tx():
            ids = []
            for spec in specs:
                spec = dict(spec)
                kind = spec.pop("kind", None)
                ids.append(self._insert_card(board_id, kind, actor=actor, **spec))
            return [self._card_dict(self._card_row(cid)) for cid in ids]

    def update_card(
        self,
        card_id: str,
        *,
        text: str | None = None,
        data: dict[str, Any] | None = None,
        color: str | None = None,
        w: float | None = None,
        h: float | None = None,
        actor: str = "chris",
    ) -> dict[str, Any]:
        self._actor(actor)
        with self._tx() as db:
            row = self._card_row(card_id)
            card = self._card_dict(row)
            if text is not None:
                card["text"] = text
            if data is not None:
                merged = {**card["data"], **data}
                card["data"] = self._normalize(card["kind"], card["text"], merged)
            if color is not None:
                card["color"] = color or None
            if w is not None and not row["column_id"]:
                card["w"] = max(160.0, min(900.0, float(w)))
            if h is not None:
                card["h"] = max(40.0, float(h))
            elif text is not None or data is not None:
                if card["kind"] not in ("column",):
                    card["h"] = layout.estimate_height(card["kind"], card["text"], card["data"], card["w"])
            # A system write (link preview, measured height) keeps the card's author.
            by = row["updated_by"] if actor == "system" else actor
            db.execute(
                "UPDATE cards SET text = ?, data = ?, color = ?, w = ?, h = ?, updated_at = ?, updated_by = ? "
                "WHERE id = ?",
                (card["text"], json.dumps(card["data"]), card["color"], card["w"], card["h"], _now(), by, card_id),
            )
            touched = [card_id]
            if card["kind"] == "column" and w is not None:
                db.execute(
                    "UPDATE cards SET w = ? WHERE column_id = ?", (card["w"] - 2 * layout.COLUMN_PAD, card_id)
                )
            if row["column_id"] and (h is not None or text is not None or data is not None):
                self._refit_column(row["column_id"])
                touched.append(row["column_id"])
            self._touch(row["board_id"], touched, actor)
            return self._card_dict(self._card_row(card_id))

    def move_card(
        self,
        card_id: str,
        *,
        x: float | None = None,
        y: float | None = None,
        column_id: str | None = None,
        index: int | None = None,
        near: str | None = None,
        side: str = "right",
        board_id: str | None = None,
        actor: str = "chris",
    ) -> dict[str, Any]:
        """Move a card on its board, into/out of a column (``column_id=""`` = out), or to another board."""
        self._actor(actor)
        with self._tx() as db:
            row = self._card_row(card_id)
            home = row["board_id"]
            touched = [card_id]
            if board_id and board_id != home:
                self._move_to_board(row, board_id, actor)
                return self._card_dict(self._card_row(card_id))
            old_column = row["column_id"]
            if column_id:
                if row["kind"] == "column":
                    raise Invalid("a column can't go inside a column")
                column = self._column(column_id, home)
                position = self._slot_position(column_id, index, exclude=card_id)
                db.execute(
                    "UPDATE cards SET column_id = ?, position = ?, w = ?, x = ?, y = ?, updated_at = ?, updated_by = ? "
                    "WHERE id = ?",
                    (column_id, position, column["w"] - 2 * layout.COLUMN_PAD, column["x"], column["y"], _now(), actor, card_id),
                )
                self._refit_column(column_id)
                touched.append(column_id)
            else:
                width = layout.DEFAULT_WIDTH[row["kind"]] if old_column else row["w"]
                existing = self._canvas_rects(home, exclude={card_id})
                if x is not None and y is not None:
                    nx, ny = float(x), float(y)
                elif near:
                    anchor = self._card_row(near)
                    if anchor["column_id"]:
                        anchor = self._card_row(anchor["column_id"])
                    nx, ny = layout.beside(Rect(anchor["x"], anchor["y"], anchor["w"], anchor["h"]), existing, width, row["h"], side)
                elif old_column:
                    col = self._card_row(old_column)
                    nx, ny = layout.beside(Rect(col["x"], col["y"], col["w"], col["h"]), existing, width, row["h"])
                else:
                    nx, ny = row["x"], row["y"]
                z = (db.execute("SELECT MAX(z) AS z FROM cards WHERE board_id = ?", (home,)).fetchone()["z"] or 0) + 1
                db.execute(
                    "UPDATE cards SET column_id = NULL, x = ?, y = ?, w = ?, z = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                    (nx, ny, width, z, _now(), actor, card_id),
                )
                if row["kind"] == "column":
                    db.execute("UPDATE cards SET x = ?, y = ? WHERE column_id = ?", (nx, ny, card_id))
            if old_column and old_column != column_id:
                self._refit_column(old_column)
                touched.append(old_column)
            self._touch(home, touched, actor)
            return self._card_dict(self._card_row(card_id))

    def _move_to_board(self, row: sqlite3.Row, board_id: str, actor: str) -> None:
        self._board_row(board_id)
        db = self._db
        child_id = json.loads(row["data"] or "{}").get("board_id") if row["kind"] == "board" else None
        if child_id and board_id in self._subtree(child_id):
            raise Invalid("a board can't be moved inside itself")
        ids = [row["id"]]
        if row["kind"] == "column":
            ids += [r["id"] for r in db.execute("SELECT id FROM cards WHERE column_id = ?", (row["id"],)).fetchall()]
        width = layout.DEFAULT_WIDTH[row["kind"]] if row["column_id"] else row["w"]
        nx, ny = layout.free_slot(self._canvas_rects(board_id), width, row["h"])
        db.execute(
            "UPDATE cards SET board_id = ?, column_id = NULL, x = ?, y = ?, w = ?, updated_at = ?, updated_by = ? WHERE id = ?",
            (board_id, nx, ny, width, _now(), actor, row["id"]),
        )
        if len(ids) > 1:
            db.execute(
                f"UPDATE cards SET board_id = ?, x = ?, y = ? WHERE id IN ({','.join('?' * (len(ids) - 1))})",
                (board_id, nx, ny, *ids[1:]),
            )
        if child_id:
            db.execute("UPDATE boards SET parent_id = ? WHERE id = ?", (board_id, child_id))
        if row["column_id"]:
            self._refit_column(row["column_id"])
        self._touch(row["board_id"], [row["id"]] + ([row["column_id"]] if row["column_id"] else []), actor)
        self._touch(board_id, ids, actor)

    def delete_card(self, card_id: str, actor: str = "chris") -> None:
        self._actor(actor)
        with self._tx() as db:
            row = self._card_row(card_id)
            touched = [card_id]
            if row["kind"] == "column":
                children = db.execute(
                    "SELECT id, kind, h FROM cards WHERE column_id = ? ORDER BY position", (card_id,)
                ).fetchall()
                existing = self._canvas_rects(row["board_id"], exclude={card_id})
                for child in children:
                    width = layout.DEFAULT_WIDTH[child["kind"]]
                    nx, ny = layout.free_slot(existing, width, child["h"])
                    db.execute(
                        "UPDATE cards SET column_id = NULL, x = ?, y = ?, w = ? WHERE id = ?", (nx, ny, width, child["id"])
                    )
                    existing.append(Rect(nx, ny, width, child["h"]))
                    touched.append(child["id"])
            elif row["kind"] == "board":
                child_id = json.loads(row["data"]).get("board_id")
                db.execute("UPDATE boards SET parent_id = NULL WHERE id = ?", (child_id,))
            db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
            if row["column_id"]:
                self._refit_column(row["column_id"])
                touched.append(row["column_id"])
            self._touch(row["board_id"], touched, actor)

    # ------------------------------------------------------------------ layout tools

    def arrange(self, board_id: str, card_ids: list[str] | None = None, mode: str = "grid", actor: str = "chris") -> list[str]:
        if mode not in ("grid", "row", "stack"):
            raise Invalid("mode must be grid, row or stack")
        self._actor(actor)
        with self._tx() as db:
            self._board_row(board_id)
            rows = db.execute(
                "SELECT id, x, y, w, h, kind FROM cards WHERE board_id = ? AND column_id IS NULL", (board_id,)
            ).fetchall()
            chosen = {r["id"]: Rect(r["x"], r["y"], r["w"], r["h"]) for r in rows if not card_ids or r["id"] in card_ids}
            if card_ids:
                missing = set(card_ids) - set(chosen)
                if missing:
                    raise Invalid(f"not on this board's canvas: {', '.join(sorted(missing))}")
            if not chosen:
                return []
            order = layout.reading_order(chosen)
            origin = (min(r.x for r in chosen.values()), min(r.y for r in chosen.values()))
            positions = layout.arrange([(cid, chosen[cid]) for cid in order], mode, origin)
            others = [Rect(r["x"], r["y"], r["w"], r["h"]) for r in rows if r["id"] not in chosen]
            placed = [Rect(positions[cid][0], positions[cid][1], chosen[cid].w, chosen[cid].h) for cid in order]
            if any(p.overlaps(o) for p in placed for o in others):
                bx = min(p.x for p in placed); by = min(p.y for p in placed)
                bw = max(p.x + p.w for p in placed) - bx; bh = max(p.y + p.h for p in placed) - by
                nx, ny = layout.free_slot(others, bw, bh)
                positions = {cid: (px - bx + nx, py - by + ny) for cid, (px, py) in positions.items()}
            for cid, (px, py) in positions.items():
                db.execute("UPDATE cards SET x = ?, y = ?, updated_by = ? WHERE id = ?", (px, py, actor, cid))
                db.execute("UPDATE cards SET x = ?, y = ? WHERE column_id = ?", (px, py, cid))
            self._touch(board_id, order, actor)
            return order

    def group_into_column(self, board_id: str, card_ids: list[str], title: str = "", actor: str = "chris") -> dict[str, Any]:
        if not card_ids:
            raise Invalid("name the cards to group")
        self._actor(actor)
        with self._tx() as db:
            rows = {r["id"]: r for r in (self._card_row(cid) for cid in card_ids)}
            for r in rows.values():
                if r["board_id"] != board_id:
                    raise Invalid(f"card {r['id']} is on another board")
                if r["kind"] == "column":
                    raise Invalid("a column can't go inside a column")
            rects = {cid: Rect(r["x"], r["y"], r["w"], r["h"]) for cid, r in rows.items() if not r["column_id"]}
            order = layout.reading_order(rects) + [cid for cid in card_ids if cid not in rects]
            origin_x = min((r.x for r in rects.values()), default=None)
            origin_y = min((r.y for r in rects.values()), default=None)
            column_id = self._insert_card(board_id, "column", text=title or "", actor=actor,
                                          x=origin_x, y=origin_y)
            for cid in order:
                self.move_card(cid, column_id=column_id, actor=actor)
            col = self._card_row(column_id)
            others = self._canvas_rects(board_id, exclude={column_id})
            me = Rect(col["x"], col["y"], col["w"], col["h"])
            if any(me.overlaps(o) for o in others):
                nx, ny = layout.free_slot(others, col["w"], col["h"])
                db.execute("UPDATE cards SET x = ?, y = ? WHERE id = ? OR column_id = ?", (nx, ny, column_id, column_id))
            return self._card_dict(self._card_row(column_id))

    def make_sub_board(self, board_id: str, card_ids: list[str], title: str, actor: str = "chris") -> dict[str, Any]:
        """Move ``card_ids`` (a column brings its cards) onto a new board nested in this one."""
        if not card_ids:
            raise Invalid("name the cards to move")
        self._actor(actor)
        with self._tx() as db:
            rows = [self._card_row(cid) for cid in card_ids]
            for r in rows:
                if r["board_id"] != board_id:
                    raise Invalid(f"card {r['id']} is on another board")
            canvas = [r for r in rows if not r["column_id"]]
            bx = min((r["x"] for r in canvas), default=layout.ORIGIN[0])
            by = min((r["y"] for r in canvas), default=layout.ORIGIN[1])
            child = self.create_board(title, parent_id=None, actor=actor)
            child_id = child["id"]
            db.execute("UPDATE boards SET parent_id = ? WHERE id = ?", (board_id, child_id))
            ox, oy = layout.ORIGIN
            moved: list[str] = []
            for r in rows:
                if r["column_id"] and r["column_id"] in card_ids:
                    continue  # travels with its column
                if r["column_id"]:
                    self.move_card(r["id"], column_id="", actor=actor)
                    r = self._card_row(r["id"])
                nx, ny = r["x"] - bx + ox, r["y"] - by + oy
                db.execute(
                    "UPDATE cards SET board_id = ?, x = ?, y = ?, updated_by = ? WHERE id = ?",
                    (child_id, nx, ny, actor, r["id"]),
                )
                moved.append(r["id"])
                if r["kind"] == "column":
                    kids = db.execute("SELECT id FROM cards WHERE column_id = ?", (r["id"],)).fetchall()
                    db.execute("UPDATE cards SET board_id = ?, x = ?, y = ? WHERE column_id = ?", (child_id, nx, ny, r["id"]))
                    moved.extend(k["id"] for k in kids)
                if r["kind"] == "board":
                    db.execute(
                        "UPDATE boards SET parent_id = ? WHERE id = ?", (child_id, json.loads(r["data"]).get("board_id"))
                    )
            self._touch(board_id, moved, actor)
            self._touch(child_id, moved, actor)
            card_id = self._insert_card(board_id, "board", data={"board_id": child_id}, actor=actor, x=bx, y=by)
            return self._card_dict(self._card_row(card_id))

    # ------------------------------------------------------------------ media

    def save_image_bytes(self, content: bytes, filename: str) -> str:
        suffix = Path(filename).suffix.lower() or ".png"
        if suffix not in IMAGE_EXTENSIONS:
            raise Invalid(f"images must be one of {', '.join(sorted(IMAGE_EXTENSIONS))}")
        if len(content) > MAX_IMAGE_BYTES:
            raise Invalid("image is larger than 25 MB")
        name = hashlib.sha256(content).hexdigest()[:20] + suffix
        target = self.config.uploads_dir / name
        if not target.exists():
            target.write_bytes(content)
        return name

    def import_image_path(self, path: str) -> str:
        source = Path(path).expanduser()
        if not source.is_file():
            raise Invalid(f"no image at {source}")
        return self.save_image_bytes(source.read_bytes(), source.name)

    def upload_path(self, name: str) -> Path:
        if "/" in name or name.startswith("."):
            raise NotFound(name)
        path = self.config.uploads_dir / name
        if not path.is_file():
            raise NotFound(name)
        return path

    def copy_upload(self, name: str, target_dir: Path) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / name
        if not target.exists():
            shutil.copy2(self.upload_path(name), target)
