"""Sidebar sections: dividers in the board list, placed by title so renames and deletes can't strand them."""

from __future__ import annotations

from conftest import W


def test_sections_round_trip_through_the_api(client) -> None:
    folder = client.post("/api/boards", json={"title": "Albums", "folder": True}, headers=W).json()

    plain = client.post("/api/sections", json={"parent_id": None, "at": None}, headers=W).json()
    named = client.post("/api/sections", json={"parent_id": folder["id"], "at": "10 · Disc 2", "title": "  Disc   2 "}, headers=W).json()
    assert plain["title"] == "" and plain["at"] is None and plain["parent_id"] is None
    assert named["title"] == "Disc 2" and named["parent_id"] == folder["id"]
    assert [s["id"] for s in client.get("/api/sections").json()] == [plain["id"], named["id"]]

    moved = client.patch(f"/api/sections/{plain['id']}", json={"parent_id": folder["id"], "at": "01"}, headers=W).json()
    assert (moved["parent_id"], moved["at"], moved["title"]) == (folder["id"], "01", "")
    renamed = client.patch(f"/api/sections/{named['id']}", json={"title": "Bonus"}, headers=W).json()
    assert (renamed["title"], renamed["at"]) == ("Bonus", "10 · Disc 2")  # renaming doesn't move it

    assert client.delete(f"/api/sections/{plain['id']}", headers=W).json()["id"] == plain["id"]
    assert [s["id"] for s in client.get("/api/sections").json()] == [named["id"]]
    assert client.delete(f"/api/sections/{plain['id']}", headers=W).status_code == 404


def test_a_section_needs_a_real_parent_and_the_write_header(client) -> None:
    assert client.post("/api/sections", json={"parent_id": "b_nope"}, headers=W).status_code == 404
    assert client.post("/api/sections", json={}).status_code == 403


def test_sections_are_not_board_content(store) -> None:
    board = store.create_board("Year")
    rev = store.board(board["id"])["rev"]
    section = store.add_section(board["id"], "05", "Second half")
    store.update_section(section["id"], title="Back half")
    assert store.board(board["id"])["rev"] == rev  # no rev bump, no undo step, no snapshot
    store.delete_section(section["id"])
    assert store.sections() == []
