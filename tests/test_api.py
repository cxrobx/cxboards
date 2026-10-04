"""The HTTP API: guards, cards of every kind, media, and the outline agents read."""

from __future__ import annotations

import time

from conftest import AGENT, PNG_1PX, W


def make_board(client, title="October sessions") -> dict:
    resp = client.post("/api/boards", json={"title": title}, headers=W)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_foreign_host_is_refused(client) -> None:
    assert client.get("/api/boards", headers={"host": "evil.example"}).status_code == 403


def test_writes_need_the_header(client) -> None:
    assert client.post("/api/boards", json={"title": "x"}).status_code == 403
    assert client.post("/api/boards", json={"title": "x"}, headers=W).status_code == 200


def test_batch_with_nested_column_and_outline(client) -> None:
    board = make_board(client)
    resp = client.post(
        f"/api/boards/{board['id']}/cards/batch",
        json={
            "cards": [
                {"kind": "note", "text": "Goal: the hook opens up"},
                {"kind": "column", "title": "Session 1", "cards": [
                    {"kind": "todo", "title": "Prep", "items": ["bounce v2", {"text": "pull drums in pre", "done": True}]},
                    {"kind": "note", "text": "Reference: Bet The Bank"},
                ]},
            ]
        },
        headers=AGENT,
    )
    assert resp.status_code == 200, resp.text
    cards = resp.json()
    assert [c["kind"] for c in cards] == ["note", "column", "todo", "note"]
    assert all(c["updated_by"] == "agent" for c in cards)
    text = client.get("/api/boards/october/outline").text
    assert "## column" in text and "Session 1" in text and "[x] pull drums in pre" in text
    assert cards[0]["id"] in text


def test_column_by_title_and_errors_are_json(client) -> None:
    board = make_board(client)
    client.post(f"/api/boards/{board['id']}/cards", json={"kind": "column", "title": "Ideas"}, headers=W)
    ok = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "x", "column": "ideas"}, headers=W)
    assert ok.status_code == 200 and ok.json()["column_id"]
    bad = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "column": "nope"}, headers=W)
    assert bad.status_code == 404 and "nope" in bad.json()["error"]
    worse = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "sticker"}, headers=W)
    assert worse.status_code == 400


def test_link_preview_fills_in(client) -> None:
    board = make_board(client)
    card = client.post(
        f"/api/boards/{board['id']}/cards", json={"kind": "link", "url": "https://youtu.be/abc"}, headers=AGENT
    ).json()
    for _ in range(50):
        data = client.get(f"/api/boards/{board['id']}").json()["cards"][0]["data"]
        if data.get("title"):
            break
        time.sleep(0.02)
    assert data["title"] == "Preview of https://youtu.be/abc"
    after = client.get(f"/api/boards/{board['id']}").json()["cards"][0]
    assert after["updated_by"] == "agent"  # the preview doesn't take authorship
    assert card["id"]


def test_image_upload_and_media(client) -> None:
    board = make_board(client)
    resp = client.post(
        f"/api/boards/{board['id']}/images",
        files={"file": ("ref.png", PNG_1PX, "image/png")},
        data={"x": "100", "y": "120"},
        headers=W,
    )
    assert resp.status_code == 200, resp.text
    card = resp.json()
    assert (card["x"], card["y"]) == (100, 120)
    media = client.get(f"/media/{card['data']['file']}")
    assert media.status_code == 200 and media.content == PNG_1PX


def test_image_by_path(client, tmp_path) -> None:
    board = make_board(client)
    src = tmp_path / "cover.png"
    src.write_bytes(PNG_1PX)
    card = client.post(
        f"/api/boards/{board['id']}/cards", json={"kind": "image", "path": str(src), "text": "cover idea"}, headers=AGENT
    ).json()
    assert card["data"]["file"].endswith(".png") and card["text"] == "cover idea"


def test_audio_streams_with_ranges(client, bounce) -> None:
    board = make_board(client)
    card = client.post(
        f"/api/boards/{board['id']}/cards", json={"kind": "audio", "path": str(bounce)}, headers=W
    ).json()
    full = client.get(f"/api/cards/{card['id']}/audio")
    assert full.status_code == 200 and full.content == bounce.read_bytes()
    part = client.get(f"/api/cards/{card['id']}/audio", headers={"Range": "bytes=0-99"})
    assert part.status_code == 206 and len(part.content) == 100


def test_move_out_of_column_and_measured_height_is_quiet(client) -> None:
    board = make_board(client)
    column = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "column", "title": "C"}, headers=W).json()
    note = client.post(
        f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "n", "column": column["id"]}, headers=W
    ).json()
    moved = client.post(f"/api/cards/{note['id']}/move", json={"column": ""}, headers=W).json()
    assert moved["column_id"] is None and moved["x"] > column["x"]
    measured = client.patch(f"/api/cards/{note['id']}", json={"h": 77}, headers=W).json()
    assert measured["h"] == 77 and measured["updated_by"] == "chris"


def test_ui_routes_serve_something(client) -> None:
    assert client.get("/").status_code == 200
    assert client.get("/b/whatever").status_code == 200


def test_changing_a_link_replaces_its_preview(client) -> None:
    board = make_board(client)
    card = client.post(
        f"/api/boards/{board['id']}/cards", json={"kind": "link", "url": "https://a.example/"}, headers=AGENT
    ).json()
    client.patch(f"/api/cards/{card['id']}", json={"url": "https://b.example/"}, headers=W)
    for _ in range(50):
        data = client.get(f"/api/boards/{board['id']}").json()["cards"][0]["data"]
        if data.get("title") == "Preview of https://b.example/":
            break
        time.sleep(0.02)
    assert data["title"] == "Preview of https://b.example/" and data["url"] == "https://b.example/"


def test_version_names_the_ui_build(client) -> None:
    # The page compares this with the build it loaded, and offers a reload when they differ.
    build = client.get("/api/version").json()["build"]
    assert build is None or (isinstance(build, str) and len(build) == 12)
