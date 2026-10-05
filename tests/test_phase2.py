"""Phase 2: lines, labels, players, swatches, image crop, uploads, and how they reach agents
(MCP, outline) and Onyx (snapshots)."""

from __future__ import annotations

import pytest
from conftest import AGENT, PNG_1PX, W

from cxboards import mcp_server as m
from cxboards.export import Exporter
from cxboards.store import Invalid, Store
from cxboards.unfurl import embed_for


# ---------------------------------------------------------------- lines

def test_lines_connect_cards_on_one_board_and_undo(store: Store) -> None:
    board = store.create_board("B")
    other = store.create_board("O")
    a = store.add_card(board["id"], "note", text="a")
    b = store.add_card(board["id"], "note", text="b")
    elsewhere = store.add_card(other["id"], "note", text="x")
    line = store.add_connector(a["id"], b["id"], label="leads to")
    assert line["arrow"] == "end" and line["curve"] is True
    with pytest.raises(Invalid, match="already connected"):
        store.add_connector(b["id"], a["id"])
    with pytest.raises(Invalid, match="same board"):
        store.add_connector(a["id"], elsewhere["id"])
    updated = store.update_connector(line["id"], style="dashed", arrow="both", curve=False, label="then")
    assert (updated["style"], updated["arrow"], updated["curve"], updated["label"]) == ("dashed", "both", False, "then")
    with pytest.raises(Invalid):
        store.update_connector(line["id"], arrow="sideways")
    store.undo(board_id=board["id"])  # the restyle
    assert store.board_state(board["id"])["connectors"][0]["label"] == "leads to"


def test_deleting_a_card_takes_its_lines_to_the_trash_and_back(store: Store) -> None:
    board = store.create_board("B")
    a = store.add_card(board["id"], "note", text="a")
    b = store.add_card(board["id"], "note", text="b")
    store.add_connector(a["id"], b["id"])
    trash_id = store.delete_card(a["id"])
    assert store.board_state(board["id"])["connectors"] == []
    store.restore(trash_id)
    assert len(store.board_state(board["id"])["connectors"]) == 1


# ---------------------------------------------------------------- labels

def test_labels_are_created_on_use_shared_and_searchable(store: Store) -> None:
    one = store.create_board("One")
    two = store.create_board("Two")
    a = store.add_card(one["id"], "note", text="hook idea")
    b = store.add_card(two["id"], "note", text="bridge idea")
    store.label_cards([a["id"], b["id"]], ["Idea"])
    store.label_cards([b["id"]], ["idea", "For Beth"])  # case-insensitive reuse
    names = {lb["name"]: lb["uses"] for lb in store.labels()}
    assert names == {"Idea": 2, "For Beth": 1}
    assert {r["card_id"] for r in store.search("label:idea")} == {a["id"], b["id"]}
    assert [r["card_id"] for r in store.search("label:idea bridge")] == [b["id"]]
    idea = next(lb for lb in store.labels() if lb["name"] == "Idea")
    store.update_label(idea["id"], name="Ideas")
    assert [lb["name"] for lb in store.board_state(one["id"])["cards"][0]["labels"]] == ["Ideas"]
    store.label_cards([a["id"]], ["Ideas"], remove=True)
    assert store.board_state(one["id"])["cards"][0]["labels"] == []
    with pytest.raises(Invalid):
        store.update_label(idea["id"], name="for beth")


# ---------------------------------------------------------------- players

@pytest.mark.parametrize(
    ("url", "provider", "src"),
    [
        ("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10", "YouTube", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
        ("https://youtu.be/dQw4w9WgXcQ", "YouTube", "https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ"),
        ("https://music.youtube.com/watch?v=abcdefghijk", "YouTube", "https://www.youtube-nocookie.com/embed/abcdefghijk"),
        ("https://vimeo.com/76979871", "Vimeo", "https://player.vimeo.com/video/76979871"),
        ("https://open.spotify.com/track/4uLU6hMCjMI75M1A2tKUQC", "Spotify", "https://open.spotify.com/embed/track/4uLU6hMCjMI75M1A2tKUQC"),
        ("https://open.spotify.com/intl-de/album/1ATL5GLyefJaxhQzSPVrLX", "Spotify", "https://open.spotify.com/embed/album/1ATL5GLyefJaxhQzSPVrLX"),
        ("https://music.apple.com/us/album/x/123?i=456", "Apple Music", "https://embed.music.apple.com/us/album/x/123?i=456"),
    ],
)
def test_embed_players(url: str, provider: str, src: str) -> None:
    embed = embed_for(url)
    assert embed and embed["provider"] == provider and embed["src"] == src


def test_embed_soundcloud_maps_bandcamp_and_none() -> None:
    sc = embed_for("https://soundcloud.com/artist/track-name")
    assert sc["provider"] == "SoundCloud" and sc["height"] == 166 and "w.soundcloud.com/player" in sc["src"]
    assert embed_for("https://soundcloud.com/artist/sets/ep")["height"] == 300
    maps = embed_for("https://www.google.com/maps/place/Electric+Lady+Studios/@40.73,-74.0,17z")
    assert maps["provider"] == "Google Maps" and "q=Electric%20Lady%20Studios" in maps["src"]
    bc = embed_for("https://x.bandcamp.com/album/y", og_video="https://bandcamp.com/EmbeddedPlayer/v=2/album=99/size=small/")
    assert bc["provider"] == "Bandcamp" and "album=99" in bc["src"] and "size=large" in bc["src"]
    assert embed_for("https://example.com/article") is None


# ---------------------------------------------------------------- swatches, crop, uploads

def test_a_hex_code_alone_becomes_a_swatch(client) -> None:
    board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
    swatch = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "#e0a33a"}, headers=W).json()
    assert swatch["kind"] == "swatch" and swatch["data"]["hex"] == "#E0A33A"
    note = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "x"}, headers=W).json()
    turned = client.patch(f"/api/cards/{note['id']}", json={"text": "fab"}, headers=W).json()
    assert turned["kind"] == "swatch" and turned["data"]["hex"] == "#FFAABB"
    bad = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "swatch", "hex": "nope"}, headers=W)
    assert bad.status_code == 400


def test_image_crop_and_rotate_are_kept_tidy(store: Store, tmp_path) -> None:
    board = store.create_board("B")
    src = tmp_path / "c.png"
    src.write_bytes(PNG_1PX)
    card = store.add_card(board["id"], "image", data={"file": store.import_image_path(str(src))})
    updated = store.update_card(card["id"], data={"crop": {"x": -5, "y": 10, "w": 150, "h": 50, "aspect": 2.5}, "rotate": 450})
    assert updated["data"]["crop"] == {"x": 0.0, "y": 10.0, "w": 100.0, "h": 50.0, "aspect": 2.5}
    assert updated["data"]["rotate"] == 90


def test_upload_without_a_card(client) -> None:
    resp = client.post("/api/uploads", files={"file": ("t.png", PNG_1PX, "image/png")}, headers=W).json()
    assert resp["url"].startswith("/media/") and client.get(resp["url"]).content == PNG_1PX


# ---------------------------------------------------------------- agents and Onyx

def test_mcp_connects_and_labels(client) -> None:
    m.set_client(client)
    try:
        m.create_board("Plan")
        added = m.add_cards("plan", [{"kind": "note", "text": "verse"}, {"kind": "note", "text": "chorus"}])
        ids = [line.split()[2].rstrip(":") for line in added.splitlines()[1:]]
        assert "Connected" in m.connect_cards(ids[0], ids[1], label="lifts into")
        outline = m.read_board("plan")
        assert "## Lines" in outline and "lifts into" in outline
        assert "idea" in m.label_cards(ids, ["idea"])
        assert "plan" in m.search("label:idea").lower()
        assert "Removed" in m.connect_cards(ids[1], ids[0], remove=True)
        assert "## Lines" not in m.read_board("plan")
    finally:
        m.set_client(None)  # type: ignore[arg-type]


def test_snapshot_draws_lines_labels_swatches_and_marks(store: Store) -> None:
    board = store.create_board("Look")
    a = store.add_card(board["id"], "note", text="==loud== part", x=80, y=80, color="#E0A33A")
    store.update_card(a["id"], data={"fill": True})
    b = store.add_card(board["id"], "swatch", data={"hex": "#2AA198"}, x=500, y=80)
    store.add_connector(a["id"], b["id"], label="becomes", style="dashed")
    store.label_cards([a["id"]], ["idea"])
    store.update_board(board["id"], in_onyx=True)
    page = Exporter(store).export_board(board["id"]).read_text()
    assert '<svg class="lines"' in page and "becomes" in page and 'stroke-dasharray' in page
    assert "<mark>loud</mark>" in page and 'class="label"' in page and "#2AA198" in page
    assert "card-note filled" in page
    assert "<script" not in page


def test_rotate_makes_a_new_file_and_keeps_the_old(config, tmp_path) -> None:
    from fastapi.testclient import TestClient

    from cxboards.app import create_app

    def fake_rotate(source, target, degrees):
        target.write_bytes(source.read_bytes() + bytes([degrees % 256]))

    app = create_app(config, unfurl=lambda u: {}, rotator=fake_rotate)
    with TestClient(app) as client:
        board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
        card = client.post(
            f"/api/boards/{board['id']}/images", files={"file": ("p.png", PNG_1PX, "image/png")}, headers=W
        ).json()
        turned = client.post(f"/api/cards/{card['id']}/rotate", json={"degrees": -90}, headers=W).json()
        assert turned["data"]["file"] != card["data"]["file"]
        assert client.get(f"/media/{card['data']['file']}").status_code == 200  # the original is kept
        client.post(f"/api/boards/{board['id']}/undo", headers=W)
        back = client.get(f"/api/boards/{board['id']}").json()["cards"][0]
        assert back["data"]["file"] == card["data"]["file"]
        assert client.post(f"/api/cards/{card['id']}/rotate", json={"degrees": 45}, headers=W).status_code == 400
