"""Moving whole boards: a board of boards is a folder (store.move_board, its route and MCP tool)."""

from __future__ import annotations

import pytest

from cxboards import mcp_server as m
from cxboards.store import Invalid, Store

from conftest import AGENT, W
from test_store import assert_no_overlaps


def board_cards(store: Store, board_id: str) -> list[dict]:
    return [c for c in store.cards(board_id) if c["kind"] == "board"]


def test_a_top_level_board_files_into_another_as_one_undo_step(store: Store) -> None:
    folder = store.create_board("Sessions")
    store.add_card(folder["id"], "note", text="what's in here")
    loose = store.create_board("October 3")
    events = []
    store.listeners.append(lambda *e: events.append(e))

    moved = store.move_board(loose["id"], folder["id"])

    assert moved["parent_id"] == folder["id"]
    [card] = board_cards(store, folder["id"])
    assert card["data"]["board_id"] == loose["id"]
    assert_no_overlaps(store, folder["id"])
    assert [b["title"] for b in store.breadcrumbs(loose["id"])] == ["Sessions", "October 3"]
    history_ids = {e[4] for e in events}
    assert len(history_ids) == 1 and {e[0] for e in events} == {folder["id"], loose["id"]}
    assert store.history_summary(history_ids.pop()).startswith("moved 1 board")

    store.undo(board_id=loose["id"])
    assert store.board(loose["id"])["parent_id"] is None
    assert board_cards(store, folder["id"]) == []


def test_a_nested_board_takes_its_card_to_the_new_parent(store: Store) -> None:
    year = store.create_board("Year")
    october = store.create_board("October", parent_id=year["id"])
    folder = store.create_board("Archive")
    [old_card] = board_cards(store, year["id"])

    store.move_board(october["id"], folder["id"])

    assert store.board(october["id"])["parent_id"] == folder["id"]
    assert board_cards(store, year["id"]) == []
    [card] = board_cards(store, folder["id"])
    assert card["id"] == old_card["id"]  # the same card moved, not a new one

    store.undo(board_id=folder["id"])
    assert store.board(october["id"])["parent_id"] == year["id"]
    assert [c["id"] for c in board_cards(store, year["id"])] == [old_card["id"]]


def test_moving_out_to_top_level_removes_the_card_and_undo_brings_it_back(store: Store) -> None:
    year = store.create_board("Year")
    october = store.create_board("October", parent_id=year["id"])
    note = store.add_card(year["id"], "note", text="see October")
    [card] = board_cards(store, year["id"])
    store.add_connector(note["id"], card["id"])
    shortcut_home = store.create_board("Shortcuts")
    store.add_card(shortcut_home["id"], "board", data={"board_id": october["id"], "shortcut": True})

    store.move_board(october["id"], None)

    assert store.board(october["id"])["parent_id"] is None
    assert board_cards(store, year["id"]) == []
    assert store.board_state(year["id"])["connectors"] == []
    assert len(board_cards(store, shortcut_home["id"])) == 1  # shortcuts stay where they are

    store.undo(board_id=october["id"])
    assert store.board(october["id"])["parent_id"] == year["id"]
    assert [c["id"] for c in board_cards(store, year["id"])] == [card["id"]]
    assert len(store.board_state(year["id"])["connectors"]) == 1


def test_a_board_cannot_go_inside_itself_or_its_own_boards(store: Store) -> None:
    year = store.create_board("Year")
    october = store.create_board("October", parent_id=year["id"])
    week = store.create_board("Week 1", parent_id=october["id"])
    for target in (year, october, week):
        with pytest.raises(Invalid, match="inside itself"):
            store.move_board(year["id"], target["id"])
    assert store.board(year["id"])["parent_id"] is None
    assert store.board(week["id"])["parent_id"] == october["id"]


def test_moving_to_where_it_already_is_changes_nothing(store: Store) -> None:
    year = store.create_board("Year")
    october = store.create_board("October", parent_id=year["id"])
    loose = store.create_board("Loose")
    events = []
    store.listeners.append(lambda *e: events.append(e))
    store.move_board(october["id"], year["id"])
    store.move_board(loose["id"], None)
    assert events == []
    assert len(board_cards(store, year["id"])) == 1


def test_a_locked_board_card_holds_its_board(store: Store) -> None:
    year = store.create_board("Year")
    october = store.create_board("October", parent_id=year["id"])
    [card] = board_cards(store, year["id"])
    store.update_card(card["id"], locked=True)
    with pytest.raises(Invalid, match="locked"):
        store.move_board(october["id"], None)
    assert store.board(october["id"])["parent_id"] == year["id"]


def test_move_route_takes_titles_and_null(client) -> None:
    client.post("/api/boards", json={"title": "Sessions"}, headers=W)
    client.post("/api/boards", json={"title": "October 3"}, headers=W)
    moved = client.post("/api/boards/October 3/move", json={"parent": "Sessions"}, headers=AGENT).json()
    assert moved["parent_id"]
    out = client.post("/api/boards/October 3/move", json={"parent": None}, headers=W).json()
    assert out["parent_id"] is None
    refused = client.post("/api/boards/Sessions/move", json={"parent": "Sessions"}, headers=W)
    assert refused.status_code == 400 and "inside itself" in refused.json()["error"]


def test_agent_files_boards_into_a_folder(client) -> None:
    m.set_client(client)
    try:
        m.create_board("Sessions")
        m.create_board("October 3")
        assert "inside Sessions" in m.move_board("October 3", "Sessions")
        assert "inside Sessions" in m.list_boards()
        assert "top-level" in m.move_board("October 3")
    finally:
        m.set_client(None)  # type: ignore[arg-type]
