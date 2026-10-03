"""Phase 3: templates, documents (Markdown, text, Word, ZIP, vault, print), drawings, clip page."""

from __future__ import annotations

import io
import shutil
import zipfile
from pathlib import Path

import pytest
from conftest import PNG_1PX, W

from cxboards import formats
from cxboards import mcp_server as m
from cxboards.config import Config
from cxboards.store import Store


@pytest.fixture
def planned(store: Store, tmp_path: Path, bounce: Path) -> dict:
    board = store.create_board("October sessions", description="Planning the month")
    column = store.add_card(board["id"], "column", text="Session 1", x=80, y=80)
    todo = store.add_card(board["id"], "todo", text="Prep", data={"items": ["bounce v2", {"text": "drums", "done": True, "indent": 1}]}, column_id=column["id"])
    image_src = tmp_path / "ref.png"
    image_src.write_bytes(PNG_1PX)
    image = store.add_card(board["id"], "image", data={"file": store.import_image_path(str(image_src))}, text="cover", x=500, y=80)
    sketch = store.add_card(board["id"], "sketch", data={"paths": [{"d": "M1,1 L20,20 Z", "color": "#222"}], "box": [100, 80]}, x=500, y=400)
    audio = store.add_card(board["id"], "audio", data={"path": str(bounce)}, x=900, y=80)
    store.add_connector(todo["id"], image["id"], label="look")
    return {"board": board, "image": image, "sketch": sketch, "audio": audio}


def test_markdown_reads_like_the_board(store: Store, planned: dict) -> None:
    md, doc = formats.bundle(store, planned["board"]["id"])
    assert md.startswith("# October sessions\n")
    assert "## Session 1" in md and "- [ ] bounce v2" in md and "  - [x] drums" in md
    assert f"![cover](media/{planned['image']['data']['file']})" in md
    assert f"media/{planned['sketch']['id']}.svg" in md
    assert "## Lines" in md and "Prep → cover: look" in md
    assert "endofworld_2.wav" in md
    text = formats.to_text(md)
    assert "**" not in text and "[image: cover]" in text and "October sessions" in text


def test_zip_carries_media_and_a_file_list(store: Store, planned: dict, bounce: Path) -> None:
    zf = zipfile.ZipFile(io.BytesIO(formats.to_zip(store, planned["board"]["id"])))
    names = set(zf.namelist())
    assert {"board.md", f"media/{planned['image']['data']['file']}", f"media/{planned['sketch']['id']}.svg", "files on disk.txt"} <= names
    assert str(bounce) in zf.read("files on disk.txt").decode()
    assert "<script" not in zf.read(f"media/{planned['sketch']['id']}.svg").decode()


@pytest.mark.skipif(not shutil.which("pandoc"), reason="pandoc not installed")
def test_word_export(store: Store, planned: dict) -> None:
    docx = formats.to_docx(store, planned["board"]["id"])
    with zipfile.ZipFile(io.BytesIO(docx)) as zf:
        assert "Session 1" in zf.read("word/document.xml").decode()


def test_vault_export_never_overwrites_an_edited_note(tmp_path: Path, planned: dict, store: Store) -> None:
    vault = tmp_path / "vault"
    first = formats.to_vault(store, planned["board"]["id"], vault)
    assert first == vault / "Inbox" / "Quick Notes" / "October sessions (CXBoards).md"
    assert f"![[{planned['image']['data']['file']}]]" in first.read_text()
    assert (vault / "Other" / "Attachments" / planned["image"]["data"]["file"]).is_file()
    assert "cxboards_id:" in first.read_text()
    again = formats.to_vault(store, planned["board"]["id"], vault)
    assert again == first  # untouched since: replaced in place
    first.write_text(first.read_text() + "\nmy own thoughts\n")
    third = formats.to_vault(store, planned["board"]["id"], vault)
    assert third.name == "October sessions (CXBoards) 2.md"
    assert "my own thoughts" in first.read_text()


def test_api_exports_and_print_view(client, bounce) -> None:
    board = client.post("/api/boards", json={"title": "Print me"}, headers=W).json()
    client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "hello **there**"}, headers=W)
    md = client.get(f"/api/boards/{board['id']}/export.md")
    assert md.status_code == 200 and "hello **there**" in md.text
    assert 'filename="print-me.md"' in md.headers["content-disposition"]
    assert client.get(f"/api/boards/{board['id']}/export.txt").text.count("**") == 0
    assert client.get(f"/api/boards/{board['id']}/export.zip").content[:2] == b"PK"
    assert client.get(f"/api/boards/{board['id']}/export.pdf").status_code == 404
    page = client.get(f"/print/{board['id']}/").text
    assert f'<base href="/print/{board["id"]}/">' in page and "print()" in page
    assert client.get("/clip").status_code == 200
    assert client.get("/api/proxy", params={"url": "file:///etc/passwd"}).status_code == 400


def test_templates(store: Store) -> None:
    template = store.create_board("Session plan")
    store.add_card(template["id"], "column", text="Goal")
    store.add_card(template["id"], "todo", text="Before FL", data={"items": ["one sentence goal"]})
    store.update_board(template["id"], is_template=True)
    month = store.create_board("November", template_id=template["id"])
    assert not month["is_template"]
    assert {c["text"] for c in store.cards(month["id"])} == {"Goal", "Before FL"}
    saved = store.duplicate_board(month["id"], title="Plan v2", as_template=True)
    assert saved["is_template"] and len(store.cards(saved["id"])) == 2


def test_drawings_keep_only_path_data(store: Store) -> None:
    board = store.create_board("B")
    sketch = store.add_card(board["id"], "sketch", data={
        "paths": [
            {"d": "M0,0 L10,10 Z", "color": "#E0A33A"},
            {"d": "M0,0\"/><script>alert(1)</script>", "color": "#000"},
            {"d": "M1,1 L2,2", "color": "red;background:url(x)"},
        ],
        "box": [200, 100],
    })
    assert sketch["data"]["paths"] == [{"d": "M0,0 L10,10 Z", "color": "#E0A33A"}]


def test_mcp_templates_and_exports(client, tmp_path) -> None:
    m.set_client(client)
    try:
        m.create_board("Session plan")
        m.add_cards("session plan", [{"kind": "column", "title": "Goal"}])
        client.patch(f"/api/boards/{client.get('/api/boards/session plan').json()['board']['id']}", json={"is_template": True}, headers=W)
        assert "TEMPLATE" in m.list_boards()
        assert "Created December" in m.create_board("December", template="session plan")
        assert "## Goal" in m.export_board("december", format="markdown")
    finally:
        m.set_client(None)  # type: ignore[arg-type]


def test_native_drop_thumbnail_from_a_path(client, tmp_path) -> None:
    board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
    link = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "link", "url": "https://example.com/"}, headers=W).json()
    image = tmp_path / "cover.png"
    image.write_bytes(PNG_1PX)
    card = client.post(f"/api/cards/{link['id']}/thumbnail", json={"path": str(image)}, headers=W).json()
    assert card["data"]["image"].startswith("/media/") and client.get(card["data"]["image"]).content == PNG_1PX
    note = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "x"}, headers=W).json()
    assert client.post(f"/api/cards/{note['id']}/thumbnail", json={"path": str(image)}, headers=W).status_code == 400
