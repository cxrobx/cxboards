"""Onyx snapshots: what lands on disk, and what never does."""

from __future__ import annotations

import pytest

from conftest import PNG_1PX

from cxboards.export import Exporter, NotInOnyx
from cxboards.store import Store


def test_snapshot_has_cards_in_reading_order_and_no_scripts(store: Store, bounce, tmp_path) -> None:
    board = store.create_board("October sessions", description="Planning the month")
    store.add_card(board["id"], "note", text="**first** <script>alert(1)</script>", x=80, y=80)
    store.add_card(board["id"], "note", text="second", x=400, y=80)
    store.add_card(board["id"], "note", text="third", x=80, y=400)
    image = tmp_path / "cover.png"
    image.write_bytes(PNG_1PX)
    store.add_card(board["id"], "image", data={"file": store.import_image_path(str(image))}, text="cover")
    store.add_card(board["id"], "audio", data={"path": str(bounce)})
    store.update_board(board["id"], in_onyx=True)
    page_path = Exporter(store).export_board(board["id"])
    page = page_path.read_text()
    assert "<title>October sessions</title>" in page
    assert "<script" not in page and "&lt;script&gt;" in page
    assert page.index("first") < page.index("second") < page.index("third")
    media = page_path.parent / "media"
    assert [p.suffix for p in media.iterdir()] == [".png"]  # images copied; audio never lands here
    assert not any(p.is_symlink() for p in media.iterdir())
    audio = [c for c in store.cards(board["id"]) if c["kind"] == "audio"][0]
    assert f'src="http://127.0.0.1:4870/api/cards/{audio["id"]}/audio"' in page


def test_rename_moves_the_snapshot_and_sweep_spares_strangers(store: Store) -> None:
    exporter = Exporter(store)
    board = store.create_board("Draft")
    store.update_board(board["id"], in_onyx=True)
    exporter.export_board(board["id"])
    stranger = store.config.export_dir / "not-ours"
    stranger.mkdir()
    (stranger / "index.html").write_text("hi")
    store.update_board(board["id"], title="October sessions")
    exporter.export_board(board["id"])
    names = sorted(p.name for p in store.config.export_dir.iterdir())
    assert names == ["not-ours", "october-sessions"]


def test_sub_board_links_between_snapshots(store: Store) -> None:
    exporter = Exporter(store)
    parent = store.create_board("Year plan")
    child = store.create_board("October", parent_id=parent["id"])
    for b in (parent, child):
        store.update_board(b["id"], in_onyx=True)
    exporter.export_all()
    page = (store.config.export_dir / "year-plan" / "index.html").read_text()
    assert 'href="../october/index.html"' in page
    child = (store.config.export_dir / "october" / "index.html").read_text()
    assert 'href="../year-plan/index.html"' in child


def test_changes_schedule_a_snapshot(client) -> None:
    import time

    board = client.post("/api/boards", json={"title": "Live"}, headers={"X-CXBoards": "1"}).json()
    client.patch(f"/api/boards/{board['id']}", json={"in_onyx": True}, headers={"X-CXBoards": "1"})
    client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "hello snapshot"}, headers={"X-CXBoards": "1"})
    page = client.app.state.config.export_dir / "live" / "index.html"
    for _ in range(100):
        if page.exists() and "hello snapshot" in page.read_text():
            break
        time.sleep(0.02)
    assert "hello snapshot" in page.read_text()


def test_onyx_is_opt_in_and_opting_out_removes_the_snapshot(store: Store) -> None:
    exporter = Exporter(store)
    board = store.create_board("Private")
    assert store.board(board["id"])["in_onyx"] is False
    assert exporter.export_all() == []
    with pytest.raises(NotInOnyx):
        exporter.export_board(board["id"])
    assert not (store.config.export_dir / "private").exists()

    store.update_board(board["id"], in_onyx=True)
    assert exporter.export_board(board["id"]).is_file()
    store.update_board(board["id"], in_onyx=False)
    exporter.sweep()
    assert not (store.config.export_dir / "private").exists()


def test_no_link_to_a_board_that_is_not_in_onyx(store: Store) -> None:
    exporter = Exporter(store)
    parent = store.create_board("Year plan")
    store.create_board("Secret", parent_id=parent["id"])
    store.update_board(parent["id"], in_onyx=True)
    page = exporter.export_board(parent["id"]).read_text()
    assert "Secret" in page and "../secret/" not in page
    assert sorted(p.name for p in store.config.export_dir.iterdir()) == ["year-plan"]


def test_toggling_over_the_api_publishes_and_unpublishes(client) -> None:
    import time

    W = {"X-CXBoards": "1"}
    board = client.post("/api/boards", json={"title": "Toggle"}, headers=W).json()
    folder = client.app.state.config.export_dir / "toggle"
    assert client.post(f"/api/boards/{board['id']}/export", headers=W).status_code >= 400
    assert client.patch(f"/api/boards/{board['id']}", json={"in_onyx": True}, headers=W).json()["in_onyx"] is True

    def wait(cond) -> bool:
        for _ in range(150):
            if cond():
                return True
            time.sleep(0.02)
        return False

    assert wait(lambda: (folder / "index.html").exists())
    client.patch(f"/api/boards/{board['id']}", json={"in_onyx": False}, headers=W)
    assert wait(lambda: not folder.exists())


def test_printing_never_puts_a_board_in_onyx(client) -> None:
    W = {"X-CXBoards": "1"}
    board = client.post("/api/boards", json={"title": "Print me"}, headers=W).json()
    assert "Print me" in client.get(f"/print/{board['id']}/").text
    assert not (client.app.state.config.export_dir / "print-me").exists()
