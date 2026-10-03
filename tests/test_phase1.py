"""Phase 1: undo/redo, trash, duplicate, move between boards, lock, z-order, search,
Finder drops, files, and migrating a database from the first release."""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

import pytest
from conftest import AGENT, W

from cxboards.app import create_app
from cxboards.locate import locate
from cxboards.store import Invalid, NotFound, Store


def texts(store: Store, board_id: str) -> set[str]:
    return {c["text"] for c in store.cards(board_id)}


# ---------------------------------------------------------------- undo / redo

def test_undo_redo_round_trip(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="a")
    store.update_card(a["id"], text="a2")
    store.move_card(a["id"], x=500, y=500)
    store.undo(board_id=board["id"])  # the move
    assert (store.card(a["id"])["x"], store.card(a["id"])["y"]) != (500, 500)
    store.undo(board_id=board["id"])  # the edit
    assert store.card(a["id"])["text"] == "a"
    store.redo(board["id"])
    assert store.card(a["id"])["text"] == "a2"
    store.undo(board_id=board["id"])
    store.undo(board_id=board["id"])  # the add
    assert store.cards(board["id"]) == []
    with pytest.raises(Invalid, match="Nothing to undo"):
        store.undo(board_id=board["id"])


def test_new_step_clears_redo(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="a")
    store.update_card(a["id"], text="a2")
    store.undo(board_id=board["id"])
    store.update_card(a["id"], text="a3")
    with pytest.raises(Invalid, match="Nothing to redo"):
        store.redo(board["id"])


def test_undo_refuses_when_an_agent_changed_the_card_since(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="mine")
    store.update_card(a["id"], text="agent's", actor="agent")
    with pytest.raises(Invalid, match="changed since"):
        store.undo(board_id=board["id"])  # Chris's add: the card has moved on
    assert store.card(a["id"])["text"] == "agent's"


def test_agent_steps_are_undone_by_id_and_not_by_cmd_z(store: Store) -> None:
    board = store.create_board("B")
    events = []
    store.listeners.append(lambda *e: events.append(e))
    store.add_cards(board["id"], [{"kind": "note", "text": "x"}, {"kind": "note", "text": "y"}], actor="agent")
    history_id = events[-1][4]
    assert store.history_summary(history_id) == "added 2 cards"
    with pytest.raises(Invalid, match="Nothing to undo"):
        store.undo(board_id=board["id"])  # Chris's stack is separate
    store.undo(history_id=history_id)
    assert store.cards(board["id"]) == []


def test_system_writes_fold_into_the_step_they_follow(store: Store) -> None:
    board = store.create_board("B")
    link = store.add_card(board["id"], "link", data={"url": "https://a.example/"})
    store.update_card(link["id"], data={"title": "A preview"}, actor="system")
    store.update_card(link["id"], h=300, actor="system")
    store.undo(board_id=board["id"])  # not blocked by the preview or the measured height
    assert store.cards(board["id"]) == []
    store.redo(board["id"])
    assert store.card(link["id"])["data"]["title"] == "A preview"


def test_undo_of_a_cross_board_move(store: Store) -> None:
    a_board = store.create_board("A")
    b_board = store.create_board("B")
    card = store.add_card(a_board["id"], "note", text="travels")
    store.move_cards([card["id"]], b_board["id"])
    assert store.card(card["id"])["board_id"] == b_board["id"]
    store.undo(board_id=a_board["id"])
    assert store.card(card["id"])["board_id"] == a_board["id"]


# ---------------------------------------------------------------- trash

def test_delete_goes_to_trash_and_restores_in_place(store: Store) -> None:
    board = store.create_board("B")
    column = store.add_card(board["id"], "column", text="C")
    kid = store.add_card(board["id"], "note", text="kid", column_id=column["id"])
    trash_id = store.delete_card(kid["id"])
    assert [t["title"] for t in store.list_trash(board["id"])] == ["kid"]
    store.restore(trash_id)
    back = store.card(kid["id"])
    assert back["column_id"] == column["id"] and store.list_trash() == []


def test_undo_of_a_delete_also_empties_its_trash_entry(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="a")
    store.delete_card(a["id"])
    store.undo(board_id=board["id"])
    assert store.card(a["id"])["text"] == "a" and store.list_trash() == []


def test_deleted_board_comes_back_with_its_nested_boards(store: Store) -> None:
    year = store.create_board("Year")
    october = store.create_board("October", parent_id=year["id"])
    week = store.create_board("Week 1", parent_id=october["id"])
    store.add_card(week["id"], "note", text="deep")
    trash_id = store.delete_board(october["id"])
    assert {b["title"] for b in store.list_boards()} == {"Year"}
    assert not any(c["kind"] == "board" for c in store.cards(year["id"]))
    store.restore(trash_id)
    assert {b["title"] for b in store.list_boards()} == {"Year", "October", "Week 1"}
    assert texts(store, week["id"]) == {"deep"}
    assert any(c["kind"] == "board" for c in store.cards(year["id"]))


def test_restoring_a_card_whose_board_is_gone_says_so(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="a")
    card_trash = store.delete_card(a["id"])
    store.delete_board(board["id"])
    with pytest.raises(Invalid, match="restore the board first"):
        store.restore(card_trash)


# ---------------------------------------------------------------- duplicate / move / lock / z

def test_duplicate_a_column_keeps_its_cards_and_lines(store: Store) -> None:
    board = store.create_board("B")
    column = store.add_card(board["id"], "column", text="Refs")
    a = store.add_card(board["id"], "note", text="a", column_id=column["id"])
    b = store.add_card(board["id"], "note", text="b")
    store._db.execute(  # a line between a and b; lines get their own API in phase 2
        "INSERT INTO connectors (id, board_id, from_id, to_id, created_at, updated_at) VALUES ('l_1', ?, ?, ?, 'now', 'now')",
        (board["id"], a["id"], b["id"]),
    )
    copies = store.duplicate_cards([column["id"], b["id"]])
    cards = store.cards(board["id"])
    assert len(cards) == 6
    new_column = next(c for c in copies if c["kind"] == "column")
    assert [c["text"] for c in cards if c["column_id"] == new_column["id"]] == ["a"]
    assert len(store.board_state(board["id"])["connectors"]) == 2


def test_duplicate_a_lone_card_in_a_column_stays_in_the_column(store: Store) -> None:
    board = store.create_board("B")
    column = store.add_card(board["id"], "column", text="C")
    a = store.add_card(board["id"], "note", text="a", column_id=column["id"])
    store.add_card(board["id"], "note", text="b", column_id=column["id"])
    (copy,) = store.duplicate_cards([a["id"]])
    kids = sorted((c for c in store.cards(board["id"]) if c["column_id"] == column["id"]), key=lambda c: c["position"])
    assert [k["id"] for k in kids][:2] == [a["id"], copy["id"]]


def test_duplicate_a_board_card_deep_copies_the_board(store: Store) -> None:
    home = store.create_board("Home")
    child = store.create_board("Refs", parent_id=home["id"])
    store.add_card(child["id"], "note", text="inside")
    card = next(c for c in store.cards(home["id"]) if c["kind"] == "board")
    (copy,) = store.duplicate_cards([card["id"]])
    assert copy["data"]["board_id"] != child["id"]
    assert texts(store, copy["data"]["board_id"]) == {"inside"}


def test_move_cards_between_boards_keeps_layout_and_drops_crossing_lines(store: Store) -> None:
    a_board = store.create_board("A")
    b_board = store.create_board("B")
    one = store.add_card(a_board["id"], "note", text="1", x=100, y=100)
    two = store.add_card(a_board["id"], "note", text="2", x=400, y=100)
    stay = store.add_card(a_board["id"], "note", text="stay", x=100, y=500)
    for lid, f, t in (("l_a", one, two), ("l_b", one, stay)):
        store._db.execute(
            "INSERT INTO connectors (id, board_id, from_id, to_id, created_at, updated_at) VALUES (?, ?, ?, ?, 'n', 'n')",
            (lid, a_board["id"], f["id"], t["id"]),
        )
    store.move_cards([one["id"], two["id"]], b_board["id"], x=0, y=0)
    moved = {c["text"]: c for c in store.cards(b_board["id"])}
    assert (moved["1"]["x"], moved["2"]["x"]) == (0, 300)
    assert [c["id"] for c in store.board_state(b_board["id"])["connectors"]] == ["l_a"]
    assert store.board_state(a_board["id"])["connectors"] == []


def test_locked_cards_refuse_moves_and_deletes(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="a")
    store.update_card(a["id"], locked=True)
    with pytest.raises(Invalid, match="locked"):
        store.move_card(a["id"], x=1, y=1, actor="agent")
    with pytest.raises(Invalid, match="locked"):
        store.delete_card(a["id"], actor="agent")
    assert store.set_positions(board["id"], {a["id"]: [9, 9]}) == []
    store.update_card(a["id"], text="still editable")


def test_z_order(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="a")
    b = store.add_card(board["id"], "note", text="b")
    assert store.update_card(a["id"], z="front")["z"] > store.card(b["id"])["z"]
    assert store.update_card(a["id"], z="back")["z"] < store.card(b["id"])["z"]


def test_set_positions_is_one_undo_step(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="a", x=0, y=0)
    b = store.add_card(board["id"], "note", text="b", x=300, y=0)
    store.set_positions(board["id"], {a["id"]: [10, 10], b["id"]: [310, 10]})
    store.undo(board_id=board["id"])
    assert (store.card(a["id"])["x"], store.card(b["id"])["x"]) == (0, 300)


# ---------------------------------------------------------------- search

def test_search_finds_cards_boards_and_labels(store: Store) -> None:
    board = store.create_board("October sessions")
    store.add_card(board["id"], "note", text="Pull the drums out of the pre-chorus")
    store.add_card(board["id"], "link", data={"url": "https://example.com/drums"})
    results = store.search("drums")
    assert {r["type"] for r in results} == {"card"} and len(results) == 2
    assert store.search("october")[0]["type"] == "board"
    assert store.search("") == []


# ---------------------------------------------------------------- Finder drops and files

def test_locate_matches_name_size_and_mtime(tmp_path: Path) -> None:
    month = tmp_path / "MuZik" / "Sep2026"
    other = tmp_path / "MuZik" / "Aug2026"
    for folder, payload in ((month, b"a" * 100), (other, b"b" * 200)):
        folder.mkdir(parents=True)
        (folder / "song.mp3").write_bytes(payload)
    target = month / "song.mp3"
    mtime_ms = target.stat().st_mtime * 1000
    found = locate("song.mp3", 100, mtime_ms, roots=[str(tmp_path)])
    assert found == [target]
    assert locate("song.mp3", 999, mtime_ms, roots=[str(tmp_path)]) == []


def test_api_locate_points_a_card_at_the_file(config, bounce) -> None:
    from fastapi.testclient import TestClient

    app = create_app(config, unfurl=lambda u: {}, locate=lambda n, s, m: [bounce] if n == bounce.name else [])
    with TestClient(app) as client:
        board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
        card = client.post(
            f"/api/boards/{board['id']}/locate",
            json={"name": bounce.name, "size": bounce.stat().st_size, "mtime": 0, "x": 10, "y": 10},
            headers=W,
        ).json()
        assert card["kind"] == "audio" and card["data"]["path"] == str(bounce)
        missing = client.post(f"/api/boards/{board['id']}/locate", json={"name": "nope.mp3", "size": 1, "mtime": 0}, headers=W)
        assert missing.status_code == 404


def test_file_fallback_copy_is_marked_and_streams(client) -> None:
    board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
    card = client.post(
        f"/api/boards/{board['id']}/files",
        files={"file": ("notes.pdf", b"%PDF-1.4 tiny", "application/pdf")},
        data={"x": "0", "y": "0"},
        headers=W,
    ).json()
    assert card["kind"] == "file" and card["data"]["copied"] and card["data"]["ext"] == "pdf"
    served = client.get(f"/api/cards/{card['id']}/file")
    assert served.status_code == 200 and served.content.startswith(b"%PDF")
    assert served.headers["content-type"] == "application/pdf"


def test_open_and_reveal_use_open(config, bounce) -> None:
    from fastapi.testclient import TestClient

    calls: list[list[str]] = []
    app = create_app(config, unfurl=lambda u: {}, opener=calls.append)
    with TestClient(app) as client:
        board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
        card = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "media", "path": str(bounce)}, headers=W).json()
        client.post(f"/api/cards/{card['id']}/open", json={}, headers=W)
        client.post(f"/api/cards/{card['id']}/open", json={"reveal": True}, headers=W)
    assert calls == [["open", str(bounce)], ["open", "-R", str(bounce)]]


def test_api_undo_and_agent_event_carries_history(client) -> None:
    board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
    client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "a"}, headers=W)
    assert client.post(f"/api/boards/{board['id']}/undo", headers=W).json()["direction"] == "undo"
    assert client.get(f"/api/boards/{board['id']}").json()["cards"] == []
    assert client.post(f"/api/boards/{board['id']}/redo", headers=W).status_code == 200
    nothing = client.post(f"/api/boards/{board['id']}/redo", headers=W)
    assert nothing.status_code == 400 and "Nothing to redo" in nothing.json()["error"]


# ---------------------------------------------------------------- migration

def test_a_first_release_database_migrates(tmp_path: Path) -> None:
    from cxboards.config import Config

    home = tmp_path / "old"
    home.mkdir()
    db = sqlite3.connect(home / "cxboards.db")
    db.executescript(
        """
        CREATE TABLE boards (id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
            parent_id TEXT, rev INTEGER NOT NULL DEFAULT 0, export_slug TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE cards (id TEXT PRIMARY KEY, board_id TEXT NOT NULL, kind TEXT NOT NULL, column_id TEXT,
            position REAL NOT NULL DEFAULT 0, x REAL NOT NULL DEFAULT 0, y REAL NOT NULL DEFAULT 0, w REAL NOT NULL DEFAULT 260,
            h REAL NOT NULL DEFAULT 120, z INTEGER NOT NULL DEFAULT 0, text TEXT NOT NULL DEFAULT '', data TEXT NOT NULL DEFAULT '{}',
            color TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, updated_by TEXT NOT NULL DEFAULT 'chris');
        INSERT INTO boards VALUES ('b_old', 'Old', '', NULL, 3, 'old', 'x', 'x');
        INSERT INTO cards (id, board_id, kind, text, created_at, updated_at) VALUES ('c_old', 'b_old', 'note', 'kept', 'x', 'x');
        """
    )
    db.commit()
    db.close()
    store = Store(Config(home=home, port=4870))
    assert store.card("c_old")["text"] == "kept" and store.card("c_old")["locked"] is False
    store.update_card("c_old", text="edited")
    store.undo(board_id="b_old")
    assert store.card("c_old")["text"] == "kept"


def test_purge_one_trash_item(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="a")
    b = store.add_card(board["id"], "note", text="b")
    ta, tb = store.delete_card(a["id"]), store.delete_card(b["id"])
    store.purge(ta)
    assert [t["id"] for t in store.list_trash()] == [tb]
    with pytest.raises(NotFound):
        store.purge(ta)


def test_deleting_a_board_tells_open_windows(store: Store) -> None:
    parent = store.create_board("Year")
    child = store.create_board("October", parent_id=parent["id"])
    events = []
    store.listeners.append(lambda *e: events.append(e))
    store.delete_board(parent["id"])
    deleted = {e[0] for e in events if e[1] == -1}
    assert deleted == {parent["id"], child["id"]}  # nested boards go too, and say so
    events.clear()
    trash_id = store.list_trash()[0]["id"]
    store.restore(trash_id)
    assert {e[0] for e in events if e[1] > 0} == {parent["id"], child["id"]}
