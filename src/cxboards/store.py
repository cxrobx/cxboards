"""SQLite storage and every board operation.

The HTTP API (and through it the MCP) is a thin shell over this class. Each
mutating method runs in one transaction, bumps the touched boards' ``rev`` and,
after commit, tells the listeners which cards changed and who changed them.
That one hook drives the live UI (SSE) and the Onyx snapshots.

Undo is journal-based. Triggers copy every changed row (before and after) into
``journal``; at commit the rows are coalesced into one ``history`` entry per
transaction. Undo puts back the before-images of exactly the rows that entry
touched, and refuses if any of them changed since (so it can't clobber an agent's
later edit). System writes (measured heights, link previews) aren't entries of
their own: they're folded into the entry that last touched the same rows.

Deleting never destroys: rows move into ``trash`` as one entry per deleted
thing and can be restored for 90 days.

Invariants (tests/ check them):
  * Agent placement never overlaps an existing card's rectangle.
  * Deleting a card never deletes other content: a column's cards return to
    the canvas, a board card's board becomes a top-level board, and the card
    itself goes to the trash.
  * One transaction = one rev bump per board = one event = one history entry.
  * Undo restores exactly what one entry changed, or refuses.
  * Nothing is written outside the CXBoards home except exports Chris asks
    for; audio, video and files on disk are only ever read.
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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterator

from . import layout
from .config import AUDIO_EXTENSIONS, IMAGE_EXTENSIONS, MAX_IMAGE_BYTES, VIDEO_EXTENSIONS, Config
from .layout import Rect

KINDS = ("note", "todo", "link", "image", "audio", "video", "file", "column", "board", "swatch", "sketch")
PATH_KINDS = ("audio", "video", "file")
ACTORS = ("chris", "agent", "system")
TRASH_DAYS = 90
HISTORY_KEEP = 400

SCHEMA = """
CREATE TABLE IF NOT EXISTS boards (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    parent_id   TEXT REFERENCES boards(id) ON DELETE SET NULL,
    rev         INTEGER NOT NULL DEFAULT 0,
    export_slug TEXT,
    is_template INTEGER NOT NULL DEFAULT 0,
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
    locked      INTEGER NOT NULL DEFAULT 0,
    tray        INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT 'chris'
);
CREATE INDEX IF NOT EXISTS cards_board ON cards(board_id);
CREATE INDEX IF NOT EXISTS cards_column ON cards(column_id);
CREATE TABLE IF NOT EXISTS connectors (
    id          TEXT PRIMARY KEY,
    board_id    TEXT NOT NULL REFERENCES boards(id) ON DELETE CASCADE,
    from_id     TEXT NOT NULL,
    to_id       TEXT NOT NULL,
    label       TEXT NOT NULL DEFAULT '',
    color       TEXT,
    style       TEXT NOT NULL DEFAULT 'solid',
    arrow       TEXT NOT NULL DEFAULT 'end',
    curve       INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    updated_by  TEXT NOT NULL DEFAULT 'chris'
);
CREATE INDEX IF NOT EXISTS connectors_board ON connectors(board_id);
CREATE TABLE IF NOT EXISTS labels (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    color       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS labels_name ON labels(lower(name));
CREATE TABLE IF NOT EXISTS card_labels (
    card_id     TEXT NOT NULL,
    label_id    TEXT NOT NULL,
    PRIMARY KEY (card_id, label_id)
);
CREATE TABLE IF NOT EXISTS trash (
    id          TEXT PRIMARY KEY,
    board_id    TEXT,
    kind        TEXT NOT NULL,
    title       TEXT NOT NULL,
    payload     TEXT NOT NULL,
    deleted_at  TEXT NOT NULL,
    actor       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chats (
    id          TEXT PRIMARY KEY,
    board_id    TEXT NOT NULL,
    title       TEXT NOT NULL,
    messages    TEXT NOT NULL DEFAULT '[]',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chats_board ON chats(board_id);
CREATE TABLE IF NOT EXISTS journal (
    seq         INTEGER PRIMARY KEY AUTOINCREMENT,
    tbl         TEXT NOT NULL,
    pk          TEXT NOT NULL,
    old         TEXT,
    new         TEXT
);
CREATE TABLE IF NOT EXISTS history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    actor       TEXT NOT NULL,
    boards      TEXT NOT NULL,
    summary     TEXT NOT NULL,
    changes     TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'done',
    created_at  TEXT NOT NULL
);
"""

# Columns added after the first release; created on old databases at startup.
ADDED_COLUMNS = [
    ("boards", "is_template", "INTEGER NOT NULL DEFAULT 0"),
    ("cards", "locked", "INTEGER NOT NULL DEFAULT 0"),
    ("cards", "tray", "INTEGER NOT NULL DEFAULT 0"),
]

JOURNALED = {
    "boards": ("id",),
    "cards": ("id",),
    "connectors": ("id",),
    "labels": ("id",),
    "card_labels": ("card_id", "label_id"),
    "trash": ("id",),
}
# Fields a conflict check ignores, and that undo never rewinds.
VOLATILE = {
    "boards": {"rev", "updated_at"},
    "cards": {"h", "updated_at", "updated_by"},
    "connectors": {"updated_at", "updated_by"},
}

ChangeListener = Callable[[str, int, list[str], str, "int | None"], None]


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


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


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
        self._migrate()
        self._columns = {t: self._table_columns(t) for t in JOURNALED}
        self._install_triggers()
        self.listeners: list[ChangeListener] = []
        self._pending: dict[str, set[str]] | None = None
        self._actors: set[str] = set()
        self._replay = False
        self._purge_trash()

    # ------------------------------------------------------------------ schema

    def _table_columns(self, table: str) -> list[str]:
        return [r["name"] for r in self._db.execute(f"PRAGMA table_info({table})").fetchall()]

    def _migrate(self) -> None:
        for table, column, ddl in ADDED_COLUMNS:
            if column not in self._table_columns(table):
                self._db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _install_triggers(self) -> None:
        for table, pk in JOURNALED.items():
            cols = self._columns[table]
            pk_new = " || '|' || ".join(f"NEW.{c}" for c in pk)
            pk_old = " || '|' || ".join(f"OLD.{c}" for c in pk)
            obj_new = "json_object(" + ", ".join(f"'{c}', NEW.{c}" for c in cols) + ")"
            obj_old = "json_object(" + ", ".join(f"'{c}', OLD.{c}" for c in cols) + ")"
            for verb, pk_expr, old, new in (
                ("INSERT", pk_new, "NULL", obj_new),
                ("UPDATE", pk_new, obj_old, obj_new),
                ("DELETE", pk_old, obj_old, "NULL"),
            ):
                name = f"journal_{table}_{verb.lower()}"
                self._db.execute(f"DROP TRIGGER IF EXISTS {name}")
                self._db.execute(
                    f"CREATE TRIGGER {name} AFTER {verb} ON {table} BEGIN "
                    f"INSERT INTO journal (tbl, pk, old, new) VALUES ('{table}', {pk_expr}, {old}, {new}); END"
                )
        self._db.execute("DELETE FROM journal")

    def _purge_trash(self) -> None:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=TRASH_DAYS)).isoformat(timespec="seconds")
        with self._lock:
            self._db.execute("DELETE FROM trash WHERE deleted_at < ?", (cutoff,))
            self._db.execute("DELETE FROM journal")

    # ------------------------------------------------------------------ transactions

    @contextmanager
    def _tx(self, replay: bool = False) -> Iterator[sqlite3.Connection]:
        with self._lock:
            outer = self._pending is None
            if outer:
                self._pending = {}
                self._actors = set()
                self._replay = replay
                self._db.execute("BEGIN IMMEDIATE")
                self._db.execute("DELETE FROM journal")
            try:
                yield self._db
                if outer:
                    revs: dict[str, int] = {}
                    for board_id in self._pending:
                        self._db.execute(
                            "UPDATE boards SET rev = rev + 1, updated_at = ? WHERE id = ?", (_now(), board_id)
                        )
                        row = self._db.execute("SELECT rev FROM boards WHERE id = ?", (board_id,)).fetchone()
                        # A board this transaction deleted is reported as rev -1, so open windows hear of it.
                        revs[board_id] = row["rev"] if row is not None else -1
                    history_id = self._record()
                    self._db.execute("DELETE FROM journal")
                    self._db.execute("COMMIT")
                    pending, self._pending = self._pending, None
                    actor = self._tx_actor()
                    for board_id, rev in revs.items():
                        for listener in list(self.listeners):
                            listener(board_id, rev, sorted(pending[board_id]), actor, history_id)
            except BaseException:
                if outer:
                    self._db.execute("ROLLBACK")
                    self._pending = None
                raise

    def batch(self):
        """Group several writes into one transaction: one rev bump, one event, one undo step."""
        return self._tx()

    def _tx_actor(self) -> str:
        for actor in ("agent", "chris"):
            if actor in self._actors:
                return actor
        return "system"

    def _touch(self, board_id: str, card_ids: list[str] | tuple[str, ...], actor: str) -> None:
        assert self._pending is not None, "_touch outside a transaction"
        self._pending.setdefault(board_id, set()).update(card_ids)
        self._actors.add(actor)

    @staticmethod
    def _actor(actor: str) -> str:
        if actor not in ACTORS:
            raise Invalid(f"actor must be one of {', '.join(ACTORS)}")
        return actor

    # ------------------------------------------------------------------ history (undo / redo)

    def _coalesced(self) -> list[list[Any]]:
        """This transaction's net row changes: [table, pk, before, after]."""
        rows = self._db.execute("SELECT tbl, pk, old, new FROM journal ORDER BY seq").fetchall()
        net: dict[tuple[str, str], list[Any]] = {}
        for r in rows:
            key = (r["tbl"], r["pk"])
            old = json.loads(r["old"]) if r["old"] else None
            new = json.loads(r["new"]) if r["new"] else None
            if key in net:
                net[key][3] = new
            else:
                net[key] = [r["tbl"], r["pk"], old, new]
        out = []
        for tbl, pk, before, after in net.values():
            if self._same(tbl, before, after):
                continue
            out.append([tbl, pk, before, after])
        return out

    @staticmethod
    def _same(tbl: str, a: dict | None, b: dict | None) -> bool:
        if a is None or b is None:
            return a is b
        skip = VOLATILE.get(tbl, set())
        return {k: v for k, v in a.items() if k not in skip} == {k: v for k, v in b.items() if k not in skip}

    def _summary(self, changes: list[list[Any]]) -> str:
        added = sum(1 for t, _, b, a in changes if t == "cards" and b is None)
        removed = sum(1 for t, _, b, a in changes if t == "cards" and a is None)
        edited = sum(1 for t, _, b, a in changes if t == "cards" and b and a)
        boards = sum(1 for t, _, b, a in changes if t == "boards" and (b is None) != (a is None))
        lines = sum(1 for t, *_ in changes if t == "connectors")
        parts = []
        if added:
            parts.append(f"added {_plural(added, 'card')}")
        if removed:
            parts.append(f"removed {_plural(removed, 'card')}")
        if edited:
            parts.append(f"changed {_plural(edited, 'card')}")
        if boards:
            parts.append(_plural(boards, "board"))
        if lines:
            parts.append(_plural(lines, "line"))
        return ", ".join(parts) or "changed the board"

    def _record(self) -> int | None:
        changes = self._coalesced()
        if not changes or self._replay:
            return None
        actor = self._tx_actor()
        if actor == "system":
            self._fold_into_history(changes)
            return None
        # A step belongs to the boards that existed before it: undoing on a new board
        # never deletes the board you're looking at.
        created = {pk for tbl, pk, before, _ in changes if tbl == "boards" and before is None}
        boards = sorted(set(self._pending or {}) - created)
        self._db.execute(
            "INSERT INTO history (actor, boards, summary, changes, created_at) VALUES (?, ?, ?, ?, ?)",
            (actor, json.dumps(boards), self._summary(changes), json.dumps(changes), _now()),
        )
        history_id = self._db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        # A new step by this actor on these boards drops their redo stack.
        for board_id in boards:
            self._db.execute(
                "DELETE FROM history WHERE actor = ? AND state = 'undone' AND id != ? "
                "AND EXISTS (SELECT 1 FROM json_each(history.boards) WHERE value = ?)",
                (actor, history_id, board_id),
            )
        self._db.execute("DELETE FROM history WHERE id <= ?", (history_id - HISTORY_KEEP,))
        return history_id

    def _fold_into_history(self, changes: list[list[Any]]) -> None:
        """A system write updates the after-image of whichever entry last touched each row."""
        recent = self._db.execute("SELECT id, changes FROM history ORDER BY id DESC LIMIT 60").fetchall()
        entries = [(r["id"], json.loads(r["changes"])) for r in recent]
        dirty: set[int] = set()
        for tbl, pk, _before, after in changes:
            for entry_id, entry in entries:
                hit = next((c for c in entry if c[0] == tbl and c[1] == pk), None)
                if hit is not None:
                    hit[3] = after
                    dirty.add(entry_id)
                    break
        for entry_id, entry in entries:
            if entry_id in dirty:
                self._db.execute("UPDATE history SET changes = ? WHERE id = ?", (json.dumps(entry), entry_id))

    def _current(self, tbl: str, pk: str) -> dict | None:
        cols = self._columns[tbl]
        keys = JOURNALED[tbl]
        where = " AND ".join(f"{k} = ?" for k in keys)
        obj = "json_object(" + ", ".join(f"'{c}', {c}" for c in cols) + ")"
        row = self._db.execute(f"SELECT {obj} AS j FROM {tbl} WHERE {where}", pk.split("|")).fetchone()
        return json.loads(row["j"]) if row else None

    def _write_image(self, tbl: str, pk: str, image: dict | None) -> None:
        keys = JOURNALED[tbl]
        where = " AND ".join(f"{k} = ?" for k in keys)
        values = pk.split("|")
        if image is None:
            self._db.execute(f"DELETE FROM {tbl} WHERE {where}", values)
            return
        exists = self._db.execute(f"SELECT 1 FROM {tbl} WHERE {where}", values).fetchone()
        skip = {"rev", "updated_at"} if tbl == "boards" else set()
        if exists:
            cols = [c for c in self._columns[tbl] if c not in keys and c not in skip and c in image]
            if cols:
                self._db.execute(
                    f"UPDATE {tbl} SET {', '.join(f'{c} = ?' for c in cols)} WHERE {where}",
                    [image[c] for c in cols] + values,
                )
        else:
            cols = [c for c in self._columns[tbl] if c in image]
            self._db.execute(
                f"INSERT INTO {tbl} ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                [image[c] for c in cols],
            )

    ORDER = ["boards", "labels", "cards", "connectors", "card_labels", "trash"]

    def _apply(self, changes: list[list[Any]], use: int) -> None:
        """Write image ``use`` (2 = before, 3 = after) for every change, parents before children."""
        writes = sorted(
            (c for c in changes if c[use] is not None), key=lambda c: self.ORDER.index(c[0])
        )
        deletes = sorted(
            (c for c in changes if c[use] is None), key=lambda c: -self.ORDER.index(c[0])
        )
        for tbl, pk, *_ in deletes:
            self._write_image(tbl, pk, None)
        for change in writes:
            self._write_image(change[0], change[1], change[use])

    def _step(self, entry: sqlite3.Row, direction: str, actor: str) -> dict[str, Any]:
        changes = json.loads(entry["changes"])
        expect, restore = (3, 2) if direction == "undo" else (2, 3)
        stale = [c for c in changes if not self._same(c[0], self._current(c[0], c[1]), c[expect])]
        if stale:
            cards = sum(1 for c in stale if c[0] == "cards")
            what = _plural(cards, "card") if cards else _plural(len(stale), "item")
            raise Invalid(f"Can't {direction}: {what} changed since. Undo the later change first.")
        with self._tx(replay=True):
            self._apply(changes, restore)
            self._db.execute(
                "UPDATE history SET state = ? WHERE id = ?", ("undone" if direction == "undo" else "done", entry["id"])
            )
            boards = json.loads(entry["boards"])
            card_ids = [c[1] for c in changes if c[0] == "cards"]
            for board_id in boards:
                if self._db.execute("SELECT 1 FROM boards WHERE id = ?", (board_id,)).fetchone():
                    self._touch(board_id, card_ids, actor)
        return {"id": entry["id"], "summary": entry["summary"], "direction": direction, "boards": boards}

    def undo(self, board_id: str | None = None, history_id: int | None = None, actor: str = "chris") -> dict[str, Any]:
        """Undo ``history_id``, or the latest step by ``actor`` that touched ``board_id``."""
        with self._lock:
            if history_id is not None:
                entry = self._db.execute(
                    "SELECT * FROM history WHERE id = ? AND state = 'done'", (history_id,)
                ).fetchone()
            else:
                entry = self._db.execute(
                    "SELECT * FROM history WHERE actor = ? AND state = 'done' "
                    "AND EXISTS (SELECT 1 FROM json_each(history.boards) WHERE value = ?) ORDER BY id DESC LIMIT 1",
                    (actor, board_id),
                ).fetchone()
            if entry is None:
                raise Invalid("Nothing to undo.")
            return self._step(entry, "undo", "chris")

    def redo(self, board_id: str, actor: str = "chris") -> dict[str, Any]:
        with self._lock:
            entry = self._db.execute(
                # A new step clears the redo stack, so every undone step is newer than every done one;
                # the most recently undone is therefore the oldest of them.
                "SELECT * FROM history WHERE actor = ? AND state = 'undone' "
                "AND EXISTS (SELECT 1 FROM json_each(history.boards) WHERE value = ?) ORDER BY id ASC LIMIT 1",
                (actor, board_id),
            ).fetchone()
            if entry is None:
                raise Invalid("Nothing to redo.")
            return self._step(entry, "redo", "chris")

    def history_summary(self, history_id: int) -> str:
        with self._lock:
            row = self._db.execute("SELECT summary FROM history WHERE id = ?", (history_id,)).fetchone()
            return row["summary"] if row else ""

    def history(self, board_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, actor, summary, state, created_at FROM history "
                "WHERE EXISTS (SELECT 1 FROM json_each(history.boards) WHERE value = ?) ORDER BY id DESC LIMIT ?",
                (board_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ boards

    def _board_row(self, board_id: str) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM boards WHERE id = ?", (board_id,)).fetchone()
        if row is None:
            raise NotFound(f"no board {board_id}")
        return row

    @staticmethod
    def _board_dict(row: sqlite3.Row) -> dict[str, Any]:
        out = {k: row[k] for k in row.keys() if k != "n"}
        out["is_template"] = bool(out.get("is_template"))
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
        self,
        title: str,
        description: str = "",
        parent_id: str | None = None,
        actor: str = "chris",
        template_id: str | None = None,
    ) -> dict[str, Any]:
        title = (title or "").strip()
        if not title:
            raise Invalid("a board needs a title")
        self._actor(actor)
        with self._tx() as db:
            if parent_id:
                self._board_row(parent_id)
            if template_id:
                board_id = self._copy_board(template_id, parent_id, title, actor, as_template=False)
                if description:
                    db.execute("UPDATE boards SET description = ? WHERE id = ?", (description, board_id))
            else:
                board_id = _new_id("b")
                now = _now()
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
        self,
        board_id: str,
        title: str | None = None,
        description: str | None = None,
        actor: str = "chris",
        is_template: bool | None = None,
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
            if is_template is not None:
                db.execute("UPDATE boards SET is_template = ? WHERE id = ?", (int(bool(is_template)), board_id))
            self._touch(board_id, [], actor)
            if row["parent_id"]:
                self._touch(row["parent_id"], self._board_card_ids(board_id), actor)
            return self._board_dict(self._board_row(board_id))

    def _board_card_ids(self, child_id: str, shortcuts: bool = True) -> list[str]:
        rows = self._db.execute(
            "SELECT id, data FROM cards WHERE kind = 'board' AND json_extract(data, '$.board_id') = ?", (child_id,)
        ).fetchall()
        return [r["id"] for r in rows if shortcuts or not json.loads(r["data"]).get("shortcut")]

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

    def _rows(self, table: str, where: str, args: list[Any]) -> list[dict[str, Any]]:
        return [dict(r) for r in self._db.execute(f"SELECT * FROM {table} WHERE {where}", args).fetchall()]

    def delete_board(self, board_id: str, actor: str = "chris") -> str:
        """Move a board, the boards nested in it and all their cards to the trash. Returns the trash id."""
        self._actor(actor)
        with self._tx() as db:
            row = self._board_row(board_id)
            doomed = sorted(self._subtree(board_id))
            marks = ",".join("?" * len(doomed))
            cards = self._rows("cards", f"board_id IN ({marks})", doomed)
            card_ids = [c["id"] for c in cards]
            cmarks = ",".join("?" * len(card_ids)) or "''"
            payload = {
                "boards": self._rows("boards", f"id IN ({marks})", doomed),
                "cards": cards,
                "connectors": self._rows("connectors", f"board_id IN ({marks})", doomed),
                "card_labels": self._rows("card_labels", f"card_id IN ({cmarks})", card_ids),
                "parent_cards": [dict(self._card_row(cid)) for cid in self._board_card_ids(board_id)],
            }
            trash_id = _new_id("t")
            db.execute(
                "INSERT INTO trash (id, board_id, kind, title, payload, deleted_at, actor) VALUES (?, ?, 'board', ?, ?, ?, ?)",
                (trash_id, row["parent_id"], row["title"], json.dumps(payload), _now(), actor),
            )
            for card in payload["parent_cards"]:
                db.execute("DELETE FROM cards WHERE id = ?", (card["id"],))
                self._touch(card["board_id"], [card["id"]], actor)
            if card_ids:
                db.execute(f"DELETE FROM card_labels WHERE card_id IN ({cmarks})", card_ids)
            db.execute(f"DELETE FROM connectors WHERE board_id IN ({marks})", doomed)
            db.execute(f"DELETE FROM cards WHERE board_id IN ({marks})", doomed)
            for bid in doomed:
                db.execute("DELETE FROM boards WHERE id = ?", (bid,))
                self._touch(bid, [], actor)  # reported as deleted (rev -1) once this commits
            return trash_id

    def duplicate_board(self, board_id: str, parent_id: str | None = None, title: str | None = None,
                        actor: str = "chris", as_template: bool = False) -> dict[str, Any]:
        self._actor(actor)
        with self._tx():
            source = self._board_row(board_id)
            new_id = self._copy_board(board_id, parent_id, title or f"{source['title']} copy", actor, as_template)
            if parent_id:
                self._insert_card(parent_id, "board", data={"board_id": new_id}, actor=actor)
            return self._board_dict(self._board_row(new_id))

    def _copy_board(self, board_id: str, parent_id: str | None, title: str, actor: str, as_template: bool) -> str:
        """Deep copy: the board, its cards, lines, labels and nested boards. Returns the new board's id."""
        source = self._board_row(board_id)
        new_id = _new_id("b")
        now = _now()
        self._db.execute(
            "INSERT INTO boards (id, title, description, parent_id, export_slug, is_template, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (new_id, title, source["description"], parent_id, self._unique_slug(title), int(as_template), now, now),
        )
        self._touch(new_id, [], actor)
        cards = self._rows("cards", "board_id = ? ORDER BY column_id IS NOT NULL", [board_id])
        self._clone_cards(cards, new_id, actor, keep_columns=True)
        return new_id

    # ------------------------------------------------------------------ cards: reads

    @staticmethod
    def _card_dict(row: sqlite3.Row | dict) -> dict[str, Any]:
        out = dict(row) if isinstance(row, dict) else {k: row[k] for k in row.keys()}
        out["data"] = json.loads(out["data"] or "{}")
        out["locked"] = bool(out.get("locked"))
        out["tray"] = bool(out.get("tray"))
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

    def _labels_for(self, card_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        if not card_ids:
            return {}
        rows = self._db.execute(
            f"SELECT cl.card_id, l.id, l.name, l.color FROM card_labels cl JOIN labels l ON l.id = cl.label_id "
            f"WHERE cl.card_id IN ({','.join('?' * len(card_ids))}) ORDER BY lower(l.name)",
            card_ids,
        ).fetchall()
        out: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            out.setdefault(r["card_id"], []).append({"id": r["id"], "name": r["name"], "color": r["color"]})
        return out

    def board_state(self, board_id: str) -> dict[str, Any]:
        with self._lock:
            board = self._board_dict(self._board_row(board_id))
            cards = self.cards(board_id)
            labels = self._labels_for([c["id"] for c in cards])
            for card in cards:
                card["labels"] = labels.get(card["id"], [])
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
            connectors = [dict(r) for r in self._db.execute(
                "SELECT * FROM connectors WHERE board_id = ? ORDER BY created_at", (board_id,)
            ).fetchall()]
            for c in connectors:
                c["curve"] = bool(c["curve"])
            return {
                "board": board,
                "cards": cards,
                "connectors": connectors,
                "breadcrumbs": self.breadcrumbs(board_id),
            }

    def reading_order(self, board_id: str) -> list[dict[str, Any]]:
        """Canvas cards top-to-bottom, left-to-right; a column's cards follow it as ``children``."""
        cards = self.board_state(board_id)["cards"]
        by_id = {c["id"]: c for c in cards}
        canvas = {
            c["id"]: Rect(c["x"], c["y"], c["w"], c["h"]) for c in cards if not c["column_id"] and not c["tray"]
        }
        out = []
        for cid in layout.reading_order(canvas):
            card = dict(by_id[cid])
            if card["kind"] == "column":
                card["children"] = sorted(
                    (c for c in cards if c["column_id"] == cid), key=lambda c: c["position"]
                )
            out.append(card)
        return out

    def search(self, query: str, limit: int = 40) -> list[dict[str, Any]]:
        """Cards and boards whose text, link, file name or label matches. ``label:name`` narrows to a label."""
        query = (query or "").strip()
        if not query:
            return []
        with self._lock:
            label = None
            match = re.match(r"^label:(\S+)\s*(.*)$", query, re.IGNORECASE)
            if match:
                label, query = match.group(1), match.group(2).strip()
            like = f"%{query.lower()}%"
            sql = (
                "SELECT c.*, b.title AS board_title FROM cards c JOIN boards b ON b.id = c.board_id "
                "WHERE (lower(c.text) LIKE ? OR lower(c.data) LIKE ?)"
            )
            args: list[Any] = [like, like]
            if label:
                sql += (
                    " AND EXISTS (SELECT 1 FROM card_labels cl JOIN labels l ON l.id = cl.label_id "
                    "WHERE cl.card_id = c.id AND lower(l.name) = lower(?))"
                )
                args.append(label)
            sql += " ORDER BY c.updated_at DESC LIMIT ?"
            args.append(limit)
            results: list[dict[str, Any]] = []
            if not label:
                for b in self._db.execute(
                    "SELECT * FROM boards WHERE lower(title) LIKE ? OR lower(description) LIKE ? "
                    "ORDER BY updated_at DESC LIMIT 10",
                    (like, like),
                ).fetchall():
                    results.append({"type": "board", "board_id": b["id"], "board_title": b["title"],
                                    "title": b["title"], "snippet": b["description"][:140]})
            for r in self._db.execute(sql, args).fetchall():
                card = self._card_dict({k: r[k] for k in r.keys() if k != "board_title"})
                data = card["data"]
                plain = re.sub(r"[*_`#>~=\[\]]+", "", card["text"] or "")
                title = (
                    plain.split("\n")[0][:80]
                    or data.get("title") or data.get("name") or data.get("url") or data.get("hex") or card["kind"]
                )
                text = " ".join((plain or data.get("description") or data.get("url") or "").split())
                idx = text.lower().find(query.lower()) if query else -1
                snippet = text[max(0, idx - 50): idx + 90] if idx >= 0 else text[:140]
                results.append({"type": "card", "kind": card["kind"], "card_id": card["id"],
                                 "board_id": card["board_id"], "board_title": r["board_title"],
                                 "title": title, "snippet": snippet})
            return results

    # ------------------------------------------------------------------ cards: writes

    def _canvas_rects(self, board_id: str, exclude: set[str] | None = None) -> list[Rect]:
        rows = self._db.execute(
            "SELECT id, x, y, w, h FROM cards WHERE board_id = ? AND column_id IS NULL AND tray = 0", (board_id,)
        ).fetchall()
        return [Rect(r["x"], r["y"], r["w"], r["h"]) for r in rows if not exclude or r["id"] not in exclude]

    def _normalize(self, kind: str, text: str, data: dict[str, Any]) -> dict[str, Any]:
        data = dict(data or {})
        if kind == "todo":
            items = data.get("items") or []
            norm = []
            for item in items:
                if isinstance(item, str):
                    norm.append({"text": item, "done": False, "indent": 0})
                elif isinstance(item, dict) and str(item.get("text", "")).strip():
                    indent = max(0, min(3, int(item.get("indent") or 0)))
                    norm.append({"text": str(item["text"]), "done": bool(item.get("done")), "indent": indent})
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
            crop = data.get("crop")
            if crop:
                box = {k: max(0.0, min(100.0, float(crop.get(k, 0)))) for k in ("x", "y", "w", "h")}
                if crop.get("aspect"):  # the crop region's pixel width / height
                    box["aspect"] = max(0.05, min(20.0, float(crop["aspect"])))
                data["crop"] = box if box["w"] > 0 and box["h"] > 0 else None
            if data.get("rotate") is not None:
                data["rotate"] = int(data["rotate"]) % 360 // 90 * 90
            if data.get("annotations"):
                data["annotations"] = self._strokes(data["annotations"])
        elif kind in PATH_KINDS:
            path = Path(str(data.get("path", ""))).expanduser()
            if not path.is_absolute():
                raise Invalid(f"a {kind} card needs an absolute path")
            suffix = path.suffix.lower()
            if kind == "audio" and suffix not in AUDIO_EXTENSIONS:
                raise Invalid(f"audio must be one of {', '.join(sorted(AUDIO_EXTENSIONS))}")
            if kind == "video" and suffix not in VIDEO_EXTENSIONS:
                raise Invalid(f"video must be one of {', '.join(sorted(VIDEO_EXTENSIONS))}")
            if not path.is_file():
                if not data.get("name"):  # a card that already exists keeps pointing while a drive is away
                    raise Invalid(f"no file at {path}")
            else:
                data.setdefault("size", path.stat().st_size)
            data["path"] = str(path)
            data.setdefault("name", path.name)
            data["ext"] = suffix.lstrip(".")
        elif kind == "board":
            if not data.get("board_id"):
                raise Invalid("a board card needs a board_id")
        elif kind == "swatch":
            hexv = str(data.get("hex", "")).strip().lstrip("#")
            if not re.fullmatch(r"[0-9a-fA-F]{6}|[0-9a-fA-F]{3}", hexv):
                raise Invalid("a swatch needs a hex colour like #E0A33A")
            if len(hexv) == 3:
                hexv = "".join(ch * 2 for ch in hexv)
            data["hex"] = "#" + hexv.upper()
            if data.get("format") not in ("hex", "rgb", "hsl", "none"):
                data["format"] = "hex"
        elif kind == "sketch":
            data.update(self._strokes(data))
        return data

    @staticmethod
    def _strokes(data: dict[str, Any]) -> dict[str, Any]:
        """A drawing's strokes: SVG path data (only path commands and numbers) and a colour each."""
        paths = data.get("paths") or []
        if not isinstance(paths, list):
            raise Invalid("a drawing's paths must be a list")
        clean = []
        for p in paths:
            if not isinstance(p, dict):
                continue
            d = str(p.get("d", ""))
            color = str(p.get("color") or "#222")
            if d and re.fullmatch(r"[MLQCZmlqcz0-9.,\s-]+", d) and re.fullmatch(r"#[0-9A-Fa-f]{3,8}|currentColor", color):
                clean.append({"d": d, "color": color})
        box = data.get("box") or [400, 300]
        return {"paths": clean, "box": [max(1.0, float(box[0])), max(1.0, float(box[1]))]}

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
        tray: bool = False,
        avoid: bool = False,
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
        if tray:
            column_id = None
        if column_id:
            column = self._column(column_id, board_id)
            if kind in ("column",):
                raise Invalid("a column can't go inside a column")
            width = column["w"] - 2 * layout.COLUMN_PAD
            position = self._slot_position(column_id, index)
            cx, cy = column["x"], column["y"]
        height = layout.estimate_height(kind, text, data, width)
        if not column_id and not tray:
            existing = self._canvas_rects(board_id)
            if x is not None and y is not None:
                cx, cy = float(x), float(y)
                if avoid:  # "about here": the nearest spot that doesn't cover a card
                    cx, cy = layout.nearest_free(existing, width, height, cx, cy)
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
            "INSERT INTO cards (id, board_id, kind, column_id, position, x, y, w, h, z, text, data, color, tray, "
            "created_at, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                card_id, board_id, kind, column_id, position, cx, cy, width, height, z,
                text or "", json.dumps(data), color, int(tray), now, now, actor,
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

    def _check_unlocked(self, row: sqlite3.Row, verb: str) -> None:
        if row["locked"]:
            raise Invalid(f"card {row['id']} is locked; unlock it before you {verb} it")

    def update_card(
        self,
        card_id: str,
        *,
        text: str | None = None,
        data: dict[str, Any] | None = None,
        color: str | None = None,
        w: float | None = None,
        h: float | None = None,
        locked: bool | None = None,
        z: str | None = None,
        kind: str | None = None,
        actor: str = "chris",
    ) -> dict[str, Any]:
        self._actor(actor)
        with self._tx() as db:
            row = self._card_row(card_id)
            card = self._card_dict(row)
            if kind is not None and kind != card["kind"]:
                if {kind, card["kind"]} != {"note", "swatch"}:
                    raise Invalid("only a note and a swatch can turn into each other")
                card["kind"] = kind
            if text is not None:
                card["text"] = text
            if data is not None:
                merged = {**card["data"], **data}
                card["data"] = self._normalize(card["kind"], card["text"], merged)
            elif kind is not None:
                card["data"] = self._normalize(card["kind"], card["text"], card["data"])
            if color is not None:
                card["color"] = color or None
            if w is not None and not row["column_id"]:
                if row["locked"]:
                    self._check_unlocked(row, "resize")
                card["w"] = max(120.0, min(1200.0, float(w)))
            if h is not None:
                card["h"] = max(40.0, float(h))
            elif text is not None or data is not None:
                if card["kind"] not in ("column",):
                    card["h"] = layout.estimate_height(card["kind"], card["text"], card["data"], card["w"])
            if locked is not None:
                card["locked"] = bool(locked)
            if z in ("front", "back"):
                agg = "MAX" if z == "front" else "MIN"
                edge = db.execute(f"SELECT {agg}(z) AS z FROM cards WHERE board_id = ?", (row["board_id"],)).fetchone()["z"] or 0
                card["z"] = edge + (1 if z == "front" else -1)
            # A system write (link preview, measured height) keeps the card's author.
            by = row["updated_by"] if actor == "system" else actor
            db.execute(
                "UPDATE cards SET kind = ?, text = ?, data = ?, color = ?, w = ?, h = ?, locked = ?, z = ?, "
                "updated_at = ?, updated_by = ? WHERE id = ?",
                (card["kind"], card["text"], json.dumps(card["data"]), card["color"], card["w"], card["h"],
                 int(card["locked"]), card["z"], _now(), by, card_id),
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
        tray: bool | None = None,
        actor: str = "chris",
    ) -> dict[str, Any]:
        """Move a card on its board, into/out of a column (``column_id=""`` = out), into or out of the
        Unsorted tray, or to another board."""
        self._actor(actor)
        with self._tx() as db:
            row = self._card_row(card_id)
            self._check_unlocked(row, "move")
            home = row["board_id"]
            touched = [card_id]
            if board_id and board_id != home:
                self.move_cards([card_id], board_id, actor=actor)
                return self._card_dict(self._card_row(card_id))
            old_column = row["column_id"]
            if tray:
                if row["kind"] == "column":
                    raise Invalid("a column can't go in the Unsorted tray")
                db.execute(
                    "UPDATE cards SET tray = 1, column_id = NULL, w = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                    (layout.DEFAULT_WIDTH[row["kind"]], _now(), actor, card_id),
                )
            elif column_id:
                if row["kind"] == "column":
                    raise Invalid("a column can't go inside a column")
                column = self._column(column_id, home)
                position = self._slot_position(column_id, index, exclude=card_id)
                db.execute(
                    "UPDATE cards SET column_id = ?, tray = 0, position = ?, w = ?, x = ?, y = ?, updated_at = ?, "
                    "updated_by = ? WHERE id = ?",
                    (column_id, position, column["w"] - 2 * layout.COLUMN_PAD, column["x"], column["y"], _now(), actor, card_id),
                )
                self._refit_column(column_id)
                touched.append(column_id)
            else:
                width = layout.DEFAULT_WIDTH[row["kind"]] if (old_column or row["tray"]) else row["w"]
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
                elif row["tray"]:
                    nx, ny = layout.free_slot(existing, width, row["h"])
                else:
                    nx, ny = row["x"], row["y"]
                z = (db.execute("SELECT MAX(z) AS z FROM cards WHERE board_id = ?", (home,)).fetchone()["z"] or 0) + 1
                db.execute(
                    "UPDATE cards SET column_id = NULL, tray = 0, x = ?, y = ?, w = ?, z = ?, updated_at = ?, "
                    "updated_by = ? WHERE id = ?",
                    (nx, ny, width, z, _now(), actor, card_id),
                )
                if row["kind"] == "column":
                    db.execute("UPDATE cards SET x = ?, y = ? WHERE column_id = ?", (nx, ny, card_id))
            if old_column and old_column != column_id:
                self._refit_column(old_column)
                touched.append(old_column)
            self._touch(home, touched, actor)
            return self._card_dict(self._card_row(card_id))

    def set_positions(self, board_id: str, positions: dict[str, list[float]], actor: str = "chris") -> list[str]:
        """Move several canvas cards at once (a multi-drag or an arrow-key nudge): one undo step."""
        self._actor(actor)
        with self._tx() as db:
            moved = []
            for card_id, (x, y) in positions.items():
                row = self._card_row(card_id)
                if row["board_id"] != board_id or row["column_id"] or row["tray"] or row["locked"]:
                    continue
                db.execute(
                    "UPDATE cards SET x = ?, y = ?, updated_at = ?, updated_by = ? WHERE id = ?",
                    (float(x), float(y), _now(), actor, card_id),
                )
                if row["kind"] == "column":
                    db.execute("UPDATE cards SET x = ?, y = ? WHERE column_id = ?", (float(x), float(y), card_id))
                moved.append(card_id)
            self._touch(board_id, moved, actor)
            return moved

    def _expand(self, card_ids: list[str]) -> list[sqlite3.Row]:
        """The cards plus, for each column among them, its children (children follow their column)."""
        rows = [self._card_row(cid) for cid in dict.fromkeys(card_ids)]
        ids = {r["id"] for r in rows}
        out = []
        for r in rows:
            if r["column_id"] in ids:
                continue
            out.append(r)
            if r["kind"] == "column":
                out.extend(
                    self._db.execute("SELECT * FROM cards WHERE column_id = ? ORDER BY position", (r["id"],)).fetchall()
                )
        return out

    def move_cards(self, card_ids: list[str], board_id: str, x: float | None = None, y: float | None = None,
                   actor: str = "chris") -> list[str]:
        """Move cards to another board, keeping their layout. Lines that would cross boards are removed."""
        self._actor(actor)
        with self._tx() as db:
            self._board_row(board_id)
            rows = self._expand(card_ids)
            for r in rows:
                self._check_unlocked(r, "move")
                if r["kind"] == "board":
                    child = json.loads(r["data"]).get("board_id")
                    if child and not json.loads(r["data"]).get("shortcut") and board_id in self._subtree(child):
                        raise Invalid("a board can't be moved inside itself")
            ids = [r["id"] for r in rows]
            top = [r for r in rows if not r["column_id"] or r["column_id"] not in ids]
            bx = min(r["x"] for r in top)
            by = min(r["y"] for r in top)
            bw = max(r["x"] + (layout.DEFAULT_WIDTH[r["kind"]] if r["column_id"] else r["w"]) for r in top) - bx
            bh = max(r["y"] + r["h"] for r in top) - by
            if x is None or y is None:
                x, y = layout.free_slot(self._canvas_rects(board_id), bw, bh)
            sources = {r["board_id"] for r in rows}
            old_columns = {r["column_id"] for r in top if r["column_id"]}
            for r in rows:
                in_moving_column = r["column_id"] in ids
                nx, ny = r["x"] - bx + float(x), r["y"] - by + float(y)
                if in_moving_column:
                    col = next(t for t in rows if t["id"] == r["column_id"])
                    nx, ny = col["x"] - bx + float(x), col["y"] - by + float(y)
                width = r["w"] if (in_moving_column or not r["column_id"]) else layout.DEFAULT_WIDTH[r["kind"]]
                db.execute(
                    "UPDATE cards SET board_id = ?, column_id = ?, tray = 0, x = ?, y = ?, w = ?, updated_at = ?, "
                    "updated_by = ? WHERE id = ?",
                    (board_id, r["column_id"] if in_moving_column else None, nx, ny, width, _now(), actor, r["id"]),
                )
                if r["kind"] == "board":
                    data = json.loads(r["data"])
                    if data.get("board_id") and not data.get("shortcut"):
                        db.execute("UPDATE boards SET parent_id = ? WHERE id = ?", (board_id, data["board_id"]))
            for col in old_columns:
                if self._db.execute("SELECT 1 FROM cards WHERE id = ?", (col,)).fetchone():
                    self._refit_column(col)
            marks = ",".join("?" * len(ids))
            db.execute(
                f"DELETE FROM connectors WHERE (from_id IN ({marks})) != (to_id IN ({marks}))", ids + ids
            )
            db.execute(f"UPDATE connectors SET board_id = ? WHERE from_id IN ({marks})", [board_id] + ids)
            for source in sources:
                self._touch(source, ids + list(old_columns), actor)
            self._touch(board_id, ids, actor)
            return ids

    def duplicate_cards(self, card_ids: list[str], board_id: str | None = None, x: float | None = None,
                        y: float | None = None, actor: str = "chris") -> list[dict[str, Any]]:
        """Copy cards (columns with their cards, board cards with their boards, lines between them).

        On the same board with no position, a copy lands just below-right of its original (or right
        after it, inside the same column)."""
        self._actor(actor)
        with self._tx():
            rows = [dict(r) for r in self._expand(card_ids)]
            if not rows:
                return []
            source_board = rows[0]["board_id"]
            target = board_id or source_board
            self._board_row(target)
            ids = {r["id"] for r in rows}
            top = [r for r in rows if not r["column_id"] or r["column_id"] not in ids]
            same_board = target == source_board
            if x is not None and y is not None:
                bx = min(r["x"] for r in top)
                by = min(r["y"] for r in top)
                for r in rows:
                    r["x"], r["y"] = r["x"] - bx + float(x), r["y"] - by + float(y)
            elif same_board:
                for r in rows:
                    r["x"], r["y"] = r["x"] + 24, r["y"] + 24
            else:
                bx = min(r["x"] for r in top)
                by = min(r["y"] for r in top)
                bw = max(r["x"] + r["w"] for r in top) - bx
                bh = max(r["y"] + r["h"] for r in top) - by
                nx, ny = layout.free_slot(self._canvas_rects(target), bw, bh)
                for r in rows:
                    r["x"], r["y"] = r["x"] - bx + nx, r["y"] - by + ny
            # A lone card copied inside its own column stays in that column, right after itself.
            keep_column = same_board and x is None
            new_ids = self._clone_cards(rows, target, actor, keep_columns=keep_column)
            return [self._card_dict(self._card_row(cid)) for cid in new_ids]

    def _clone_cards(self, rows: list[dict[str, Any]], board_id: str, actor: str, keep_columns: bool) -> list[str]:
        """Insert copies of ``rows`` on ``board_id``. Returns the new ids of the top-level copies."""
        db = self._db
        mapping = {r["id"]: _new_id("c") for r in rows}
        now = _now()
        z = (db.execute("SELECT MAX(z) AS z FROM cards WHERE board_id = ?", (board_id,)).fetchone()["z"] or 0)
        tops = []
        touched_columns: set[str] = set()
        for r in sorted(rows, key=lambda r: (r["column_id"] is not None, r["z"])):
            data = json.loads(r["data"] or "{}")
            if r["kind"] == "board" and data.get("board_id") and not data.get("shortcut"):
                child = data["board_id"]
                if self._db.execute("SELECT 1 FROM boards WHERE id = ?", (child,)).fetchone():
                    title = self._board_row(child)["title"]
                    data["board_id"] = self._copy_board(child, board_id, title, actor, as_template=False)
            if r["column_id"] in mapping:
                column_id, position = mapping[r["column_id"]], r["position"]
            elif r["column_id"] and keep_columns:
                column_id = r["column_id"]
                later = db.execute(
                    "SELECT MIN(position) AS p FROM cards WHERE column_id = ? AND position > ?", (column_id, r["position"])
                ).fetchone()["p"]
                position = (r["position"] + later) / 2 if later is not None else r["position"] + 1
                touched_columns.add(column_id)
            else:
                column_id, position = None, r["position"]
            width = r["w"] if (column_id or not r["column_id"]) else layout.DEFAULT_WIDTH[r["kind"]]
            z += 1
            db.execute(
                "INSERT INTO cards (id, board_id, kind, column_id, position, x, y, w, h, z, text, data, color, locked, "
                "tray, created_at, updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                (mapping[r["id"]], board_id, r["kind"], column_id, position, r["x"], r["y"], width, r["h"], z,
                 r["text"], json.dumps(data), r["color"], r["tray"], now, now, actor),
            )
            if column_id is None or column_id not in mapping.values():
                tops.append(mapping[r["id"]])
        for col in touched_columns:
            self._refit_column(col)
        marks = ",".join("?" * len(mapping))
        old = list(mapping)
        for c in self._rows("connectors", f"from_id IN ({marks}) AND to_id IN ({marks})", old + old):
            db.execute(
                "INSERT INTO connectors (id, board_id, from_id, to_id, label, color, style, arrow, curve, created_at, "
                "updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (_new_id("l"), board_id, mapping[c["from_id"]], mapping[c["to_id"]], c["label"], c["color"],
                 c["style"], c["arrow"], c["curve"], now, now, actor),
            )
        for cl in self._rows("card_labels", f"card_id IN ({marks})", old):
            db.execute("INSERT OR IGNORE INTO card_labels (card_id, label_id) VALUES (?, ?)",
                       (mapping[cl["card_id"]], cl["label_id"]))
        self._touch(board_id, list(mapping.values()) + list(touched_columns), actor)
        return tops

    def delete_card(self, card_id: str, actor: str = "chris") -> str:
        """Move a card to the trash. Returns the trash id."""
        return self.delete_cards([card_id], actor)[0]

    def delete_cards(self, card_ids: list[str], actor: str = "chris") -> list[str]:
        self._actor(actor)
        with self._tx() as db:
            trash_ids = []
            for card_id in dict.fromkeys(card_ids):
                row = db.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
                if row is None:
                    continue  # went with an earlier card in this batch
                self._check_unlocked(row, "delete")
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
                    data = json.loads(row["data"])
                    if not data.get("shortcut"):
                        db.execute("UPDATE boards SET parent_id = NULL WHERE id = ?", (data.get("board_id"),))
                payload = {
                    "cards": [dict(row)],
                    "connectors": self._rows("connectors", "from_id = ? OR to_id = ?", [card_id, card_id]),
                    "card_labels": self._rows("card_labels", "card_id = ?", [card_id]),
                }
                trash_id = _new_id("t")
                db.execute(
                    "INSERT INTO trash (id, board_id, kind, title, payload, deleted_at, actor) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (trash_id, row["board_id"], row["kind"], self._title_of(row), json.dumps(payload), _now(), actor),
                )
                db.execute("DELETE FROM connectors WHERE from_id = ? OR to_id = ?", (card_id, card_id))
                db.execute("DELETE FROM card_labels WHERE card_id = ?", (card_id,))
                db.execute("DELETE FROM cards WHERE id = ?", (card_id,))
                if row["column_id"]:
                    if db.execute("SELECT 1 FROM cards WHERE id = ?", (row["column_id"],)).fetchone():
                        self._refit_column(row["column_id"])
                        touched.append(row["column_id"])
                self._touch(row["board_id"], touched, actor)
                trash_ids.append(trash_id)
            return trash_ids

    def _title_of(self, row: sqlite3.Row | dict) -> str:
        data = json.loads(row["data"] or "{}")
        if row["kind"] == "board" and data.get("board_id"):
            child = self._db.execute("SELECT title FROM boards WHERE id = ?", (data["board_id"],)).fetchone()
            if child:
                return child["title"]
        text = " ".join((row["text"] or "").split())
        return (text or data.get("title") or data.get("name") or data.get("url") or data.get("hex") or row["kind"])[:80]

    # ------------------------------------------------------------------ trash

    def list_trash(self, board_id: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            sql = "SELECT id, board_id, kind, title, deleted_at, actor FROM trash"
            args: list[Any] = []
            if board_id:
                sql += " WHERE board_id = ?"
                args.append(board_id)
            rows = self._db.execute(sql + " ORDER BY deleted_at DESC, rowid DESC", args).fetchall()
            return [dict(r) for r in rows]

    def restore(self, trash_id: str, actor: str = "chris") -> dict[str, Any]:
        """Put a trashed card or board back where it was."""
        self._actor(actor)
        with self._tx() as db:
            row = db.execute("SELECT * FROM trash WHERE id = ?", (trash_id,)).fetchone()
            if row is None:
                raise NotFound(f"nothing in the trash called {trash_id}")
            payload = json.loads(row["payload"])
            boards = {b["id"] for b in payload.get("boards", [])}
            # Parents before children: a nested board's parent_id must exist when it goes back in.
            pending, ordered = list(payload.get("boards", [])), []
            while pending:
                ready = [b for b in pending if b["parent_id"] not in {p["id"] for p in pending}] or pending
                ordered.extend(ready)
                pending = [b for b in pending if b not in ready]
            for b in ordered:
                parent = b["parent_id"]
                if parent and parent not in boards and not db.execute("SELECT 1 FROM boards WHERE id = ?", (parent,)).fetchone():
                    b = {**b, "parent_id": None}
                self._write_image("boards", b["id"], b)
                self._touch(b["id"], [], actor)
            for c in payload.get("cards", []):
                if not db.execute("SELECT 1 FROM boards WHERE id = ?", (c["board_id"],)).fetchone():
                    raise Invalid("its board is in the trash too; restore the board first")
                if c["column_id"] and not db.execute("SELECT 1 FROM cards WHERE id = ?", (c["column_id"],)).fetchone():
                    c = {**c, "column_id": None}
                self._write_image("cards", c["id"], c)
                if c["column_id"]:
                    self._refit_column(c["column_id"])
                self._touch(c["board_id"], [c["id"]], actor)
                if c["kind"] == "board":
                    data = json.loads(c["data"])
                    if not data.get("shortcut") and data.get("board_id"):
                        db.execute("UPDATE boards SET parent_id = ? WHERE id = ? AND parent_id IS NULL",
                                   (c["board_id"], data["board_id"]))
            for c in payload.get("parent_cards", []):
                if db.execute("SELECT 1 FROM boards WHERE id = ?", (c["board_id"],)).fetchone():
                    self._write_image("cards", c["id"], c)
                    self._touch(c["board_id"], [c["id"]], actor)
            for conn in payload.get("connectors", []):
                ends = db.execute("SELECT COUNT(*) AS n FROM cards WHERE id IN (?, ?)", (conn["from_id"], conn["to_id"])).fetchone()["n"]
                if ends == 2:
                    self._write_image("connectors", conn["id"], conn)
            for cl in payload.get("card_labels", []):
                if db.execute("SELECT 1 FROM labels WHERE id = ?", (cl["label_id"],)).fetchone():
                    db.execute("INSERT OR IGNORE INTO card_labels (card_id, label_id) VALUES (?, ?)",
                               (cl["card_id"], cl["label_id"]))
            db.execute("DELETE FROM trash WHERE id = ?", (trash_id,))
            self._actors.add(actor)
            first_board = next(iter(boards), None) or (payload.get("cards") or [{}])[0].get("board_id")
            return {"restored": trash_id, "board_id": first_board, "kind": row["kind"]}

    def purge(self, trash_id: str, actor: str = "chris") -> None:
        """Delete one thing from the trash for good."""
        self._actor(actor)
        with self._tx() as db:
            if db.execute("DELETE FROM trash WHERE id = ?", (trash_id,)).rowcount == 0:
                raise NotFound(f"nothing in the trash called {trash_id}")
            self._actors.add(actor)

    def empty_trash(self, actor: str = "chris") -> int:
        self._actor(actor)
        with self._tx() as db:
            n = db.execute("SELECT COUNT(*) AS n FROM trash").fetchone()["n"]
            db.execute("DELETE FROM trash")
            self._actors.add(actor)
            return n

    # ------------------------------------------------------------------ lines between cards

    def _connector_row(self, connector_id: str) -> sqlite3.Row:
        row = self._db.execute("SELECT * FROM connectors WHERE id = ?", (connector_id,)).fetchone()
        if row is None:
            raise NotFound(f"no line {connector_id}")
        return row

    @staticmethod
    def _connector_dict(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["curve"] = bool(out["curve"])
        return out

    @staticmethod
    def _check_line_style(style: str | None, arrow: str | None) -> None:
        if style is not None and style not in ("solid", "dashed"):
            raise Invalid("a line's style is solid or dashed")
        if arrow is not None and arrow not in ("end", "both", "none"):
            raise Invalid("a line's arrow is end, both or none")

    def add_connector(self, from_id: str, to_id: str, label: str = "", color: str | None = None,
                      style: str = "solid", arrow: str = "end", curve: bool = True, actor: str = "chris") -> dict[str, Any]:
        self._actor(actor)
        self._check_line_style(style, arrow)
        with self._tx() as db:
            a, b = self._card_row(from_id), self._card_row(to_id)
            if from_id == to_id:
                raise Invalid("a line needs two different cards")
            if a["board_id"] != b["board_id"]:
                raise Invalid("both cards must be on the same board")
            existing = db.execute(
                "SELECT id FROM connectors WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)",
                (from_id, to_id, to_id, from_id),
            ).fetchone()
            if existing:
                raise Invalid(f"those cards are already connected ({existing['id']})")
            connector_id, now = _new_id("l"), _now()
            db.execute(
                "INSERT INTO connectors (id, board_id, from_id, to_id, label, color, style, arrow, curve, created_at, "
                "updated_at, updated_by) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (connector_id, a["board_id"], from_id, to_id, label or "", color, style, arrow, int(curve), now, now, actor),
            )
            self._touch(a["board_id"], [from_id, to_id], actor)
            return self._connector_dict(self._connector_row(connector_id))

    def update_connector(self, connector_id: str, actor: str = "chris", **fields: Any) -> dict[str, Any]:
        self._actor(actor)
        self._check_line_style(fields.get("style"), fields.get("arrow"))
        with self._tx() as db:
            row = self._connector_row(connector_id)
            allowed = {k: v for k, v in fields.items() if k in ("label", "color", "style", "arrow", "curve") and v is not None}
            if "curve" in allowed:
                allowed["curve"] = int(bool(allowed["curve"]))
            if allowed:
                sets = ", ".join(f"{k} = ?" for k in allowed)
                db.execute(
                    f"UPDATE connectors SET {sets}, updated_at = ?, updated_by = ? WHERE id = ?",
                    [*allowed.values(), _now(), actor, connector_id],
                )
            self._touch(row["board_id"], [row["from_id"], row["to_id"]], actor)
            return self._connector_dict(self._connector_row(connector_id))

    def delete_connector(self, connector_id: str, actor: str = "chris") -> None:
        self._actor(actor)
        with self._tx() as db:
            row = self._connector_row(connector_id)
            db.execute("DELETE FROM connectors WHERE id = ?", (connector_id,))
            self._touch(row["board_id"], [row["from_id"], row["to_id"]], actor)

    # ------------------------------------------------------------------ labels

    LABEL_COLORS = ["#E0A33A", "#CB4B16", "#859900", "#2AA198", "#6C71C4", "#D33682", "#268BD2", "#B58900"]

    def labels(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT l.*, (SELECT COUNT(*) FROM card_labels cl WHERE cl.label_id = l.id) AS uses "
                "FROM labels l ORDER BY lower(l.name)"
            ).fetchall()
            return [dict(r) for r in rows]

    def _label_by_name(self, name: str, create: bool) -> sqlite3.Row | None:
        name = " ".join((name or "").split())
        if not name:
            raise Invalid("a label needs a name")
        row = self._db.execute("SELECT * FROM labels WHERE lower(name) = lower(?)", (name,)).fetchone()
        if row is None and create:
            count = self._db.execute("SELECT COUNT(*) AS n FROM labels").fetchone()["n"]
            label_id = _new_id("lb")
            self._db.execute(
                "INSERT INTO labels (id, name, color, created_at) VALUES (?, ?, ?, ?)",
                (label_id, name, self.LABEL_COLORS[count % len(self.LABEL_COLORS)], _now()),
            )
            row = self._db.execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone()
        return row

    def _touch_label_users(self, label_id: str, actor: str) -> None:
        rows = self._db.execute(
            "SELECT c.board_id, c.id FROM card_labels cl JOIN cards c ON c.id = cl.card_id WHERE cl.label_id = ?",
            (label_id,),
        ).fetchall()
        for r in rows:
            self._touch(r["board_id"], [r["id"]], actor)
        self._actors.add(actor)

    def label_cards(self, card_ids: list[str], names: list[str], remove: bool = False, actor: str = "chris") -> list[dict[str, Any]]:
        """Add (or with ``remove``, take off) labels by name; missing labels are created."""
        self._actor(actor)
        with self._tx() as db:
            for card_id in card_ids:
                row = self._card_row(card_id)
                for name in names:
                    label = self._label_by_name(name, create=not remove)
                    if label is None:
                        continue
                    if remove:
                        db.execute("DELETE FROM card_labels WHERE card_id = ? AND label_id = ?", (card_id, label["id"]))
                    else:
                        db.execute("INSERT OR IGNORE INTO card_labels (card_id, label_id) VALUES (?, ?)", (card_id, label["id"]))
                self._touch(row["board_id"], [card_id], actor)
            labels = self._labels_for(card_ids)
            return [{"card_id": cid, "labels": labels.get(cid, [])} for cid in card_ids]

    def update_label(self, label_id: str, name: str | None = None, color: str | None = None, actor: str = "chris") -> dict[str, Any]:
        self._actor(actor)
        with self._tx() as db:
            row = db.execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone()
            if row is None:
                raise NotFound(f"no label {label_id}")
            if name is not None:
                name = " ".join(name.split())
                clash = db.execute("SELECT id FROM labels WHERE lower(name) = lower(?) AND id != ?", (name, label_id)).fetchone()
                if not name or clash:
                    raise Invalid("that label name is empty or taken")
                db.execute("UPDATE labels SET name = ? WHERE id = ?", (name, label_id))
            if color is not None:
                db.execute("UPDATE labels SET color = ? WHERE id = ?", (color, label_id))
            self._touch_label_users(label_id, actor)
            return dict(db.execute("SELECT * FROM labels WHERE id = ?", (label_id,)).fetchone())

    def delete_label(self, label_id: str, actor: str = "chris") -> None:
        self._actor(actor)
        with self._tx() as db:
            self._touch_label_users(label_id, actor)
            db.execute("DELETE FROM card_labels WHERE label_id = ?", (label_id,))
            db.execute("DELETE FROM labels WHERE id = ?", (label_id,))

    # ------------------------------------------------------------------ layout tools

    def arrange(self, board_id: str, card_ids: list[str] | None = None, mode: str = "grid", actor: str = "chris") -> list[str]:
        if mode not in ("grid", "row", "stack"):
            raise Invalid("mode must be grid, row or stack")
        self._actor(actor)
        with self._tx() as db:
            self._board_row(board_id)
            rows = db.execute(
                "SELECT id, x, y, w, h, kind, locked FROM cards WHERE board_id = ? AND column_id IS NULL AND tray = 0",
                (board_id,),
            ).fetchall()
            chosen = {
                r["id"]: Rect(r["x"], r["y"], r["w"], r["h"])
                for r in rows if (not card_ids or r["id"] in card_ids) and not r["locked"]
            }
            if card_ids:
                missing = set(card_ids) - {r["id"] for r in rows}
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
                self._check_unlocked(r, "move")
            rects = {cid: Rect(r["x"], r["y"], r["w"], r["h"]) for cid, r in rows.items() if not r["column_id"] and not r["tray"]}
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
        with self._tx():
            rows = [self._card_row(cid) for cid in card_ids]
            for r in rows:
                if r["board_id"] != board_id:
                    raise Invalid(f"card {r['id']} is on another board")
            canvas = [r for r in rows if not r["column_id"]]
            bx = min((r["x"] for r in canvas), default=layout.ORIGIN[0])
            by = min((r["y"] for r in canvas), default=layout.ORIGIN[1])
            child = self.create_board(title, parent_id=None, actor=actor)
            self._db.execute("UPDATE boards SET parent_id = ? WHERE id = ?", (board_id, child["id"]))
            self.move_cards(card_ids, child["id"], x=layout.ORIGIN[0], y=layout.ORIGIN[1], actor=actor)
            card_id = self._insert_card(board_id, "board", data={"board_id": child["id"]}, actor=actor, x=bx, y=by)
            return self._card_dict(self._card_row(card_id))

    # ------------------------------------------------------------------ chats (Ask)
    # Conversations about a board. Not board content: no undo, no trash, no rev bump.

    def chats(self, board_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id, board_id, title, updated_at, json_array_length(messages) AS n FROM chats "
                "WHERE board_id = ? ORDER BY updated_at DESC, rowid DESC",
                (board_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def chat(self, chat_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._db.execute("SELECT * FROM chats WHERE id = ?", (chat_id,)).fetchone()
            if row is None:
                raise NotFound(f"no chat {chat_id}")
            out = dict(row)
            out["messages"] = json.loads(out["messages"])
            return out

    def start_chat(self, board_id: str, title: str) -> str:
        with self._lock:
            self._board_row(board_id)
            chat_id, now = _new_id("ch"), _now()
            title = " ".join(title.split())[:70] or "Chat"
            self._db.execute(
                "INSERT INTO chats (id, board_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (chat_id, board_id, title, now, now),
            )
            return chat_id

    def add_message(self, chat_id: str, message: dict[str, Any]) -> None:
        with self._lock:
            chat = self.chat(chat_id)
            chat["messages"].append({**message, "at": _now()})
            self._db.execute(
                "UPDATE chats SET messages = ?, updated_at = ? WHERE id = ?",
                (json.dumps(chat["messages"]), _now(), chat_id),
            )

    def delete_chat(self, chat_id: str) -> None:
        with self._lock:
            if self._db.execute("DELETE FROM chats WHERE id = ?", (chat_id,)).rowcount == 0:
                raise NotFound(f"no chat {chat_id}")

    # ------------------------------------------------------------------ media

    def save_image_bytes(self, content: bytes, filename: str) -> str:
        suffix = Path(filename).suffix.lower() or ".png"
        if suffix not in IMAGE_EXTENSIONS:
            raise Invalid(f"images must be one of {', '.join(sorted(IMAGE_EXTENSIONS))}")
        if len(content) > MAX_IMAGE_BYTES:
            raise Invalid("image is larger than 25 MB")
        return self._save_upload(content, suffix)

    def _save_upload(self, content: bytes, suffix: str) -> str:
        name = hashlib.sha256(content).hexdigest()[:20] + suffix
        target = self.config.uploads_dir / name
        if not target.exists():
            target.write_bytes(content)
        return name

    def save_file_bytes(self, content: bytes, filename: str) -> Path:
        """A copy of a dropped file that couldn't be found on disk. Returns its path in uploads."""
        return self.config.uploads_dir / self._save_upload(content, Path(filename).suffix.lower())

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
