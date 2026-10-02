"""Onyx snapshots: what lands on disk, and what never does."""

from __future__ import annotations

from conftest import PNG_1PX

from cxboards.export import Exporter
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
    store.create_board("October", parent_id=parent["id"])
    exporter.export_all()
    page = (store.config.export_dir / "year-plan" / "index.html").read_text()
    assert 'href="../october/index.html"' in page
    child = (store.config.export_dir / "october" / "index.html").read_text()
    assert 'href="../year-plan/index.html"' in child


def test_changes_schedule_a_snapshot(client) -> None:
    import time

    board = client.post("/api/boards", json={"title": "Live"}, headers={"X-CXBoards": "1"}).json()
    client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "hello snapshot"}, headers={"X-CXBoards": "1"})
    page = client.app.state.config.export_dir / "live" / "index.html"
    for _ in range(100):
        if page.exists() and "hello snapshot" in page.read_text():
            break
        time.sleep(0.02)
    assert "hello snapshot" in page.read_text()
