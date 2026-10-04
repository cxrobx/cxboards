"""Per-board themes: presets, custom colours kept readable, carried by copies and templates,
undoable, worn by the Onyx snapshot, and settable by agents."""

from __future__ import annotations

import pytest
from conftest import W

from cxboards import mcp_server as m
from cxboards import themes
from cxboards.export import Exporter
from cxboards.store import Invalid, Store


@pytest.mark.parametrize("name", [n for n in themes.PRESETS if n != "vault"])
def test_every_preset_is_readable(name: str) -> None:
    pal = themes.palette({"preset": name})
    assert themes.contrast(pal["ink"], pal["canvas"]) >= 7
    assert themes.contrast(pal["muted"], pal["canvas"]) >= 4.5
    assert themes.contrast(pal["accent"], pal["canvas"]) >= 2.2
    assert themes.contrast(pal["onAccent"], pal["accent"]) >= 4.5


def test_vault_is_the_apps_own_look() -> None:
    # No theme of its own (None) wears the parent's; "vault" said on purpose is kept, and is the app's look.
    assert themes.normalize(None) is None and themes.normalize("vault") == {"preset": "vault"}
    assert themes.palette(None) is None and themes.palette({"preset": "vault"}) is None


def test_custom_colours_are_corrected_not_refused() -> None:
    # Grey on grey, and an accent the same as the ground.
    theme = themes.normalize({"preset": "custom", "ground": "#777", "ink": "#888", "accent": "#777777"})
    pal = themes.palette(theme)
    assert themes.contrast(pal["ink"], pal["canvas"]) >= 4.5
    assert pal["accent"] == pal["ink"]  # too faint to see: falls back to the ink
    with pytest.raises(themes.ThemeError):
        themes.normalize({"preset": "custom", "ground": "red", "ink": "#000"})
    with pytest.raises(themes.ThemeError):
        themes.normalize("neon")


def test_chris_x_keeps_its_brand() -> None:
    pal = themes.palette({"preset": "chrisx"})
    assert (pal["canvas"], pal["card"], pal["ink"], pal["accent"], pal["muted"]) == (
        "#000000", "#000000", "#F3ECDD", "#F3ECDD", "#A89E89")
    assert pal["radius"] == "0px" and "Fraunces" in pal["fontDisplay"] and pal["fontWeight"] == "300"


def test_theme_lives_on_the_board_and_travels(store: Store) -> None:
    board = store.create_board("EP")
    store.update_board(board["id"], theme="film")
    state = store.board_state(board["id"])
    assert state["board"]["theme"] == {"preset": "film"} and state["palette"]["accent"] == "#E8A04F"
    store.update_board(board["id"], is_template=True)
    copy = store.create_board("EP 2", template_id=board["id"])
    assert copy["theme"] == {"preset": "film"}
    store.undo(board_id=board["id"])  # the template flag
    store.undo(board_id=board["id"])  # the theme
    assert store.board(board["id"])["theme"] is None
    with pytest.raises(Invalid):
        store.update_board(board["id"], theme={"preset": "custom", "ground": "nope", "ink": "#000"})
    store.update_board(board["id"], title="EP one")  # leaving theme out keeps it
    assert store.board(board["id"])["theme"] is None


def test_a_board_card_and_the_sidebar_show_the_boards_colours(store: Store) -> None:
    parent = store.create_board("Year")
    child = store.create_board("October", parent_id=parent["id"])
    store.update_board(child["id"], theme="midnight")
    card = next(c for c in store.board_state(parent["id"])["cards"] if c["kind"] == "board")
    assert card["board"]["swatch"]["ground"] == "#0E1626"
    listed = {b["id"]: b["swatch"] for b in store.list_boards()}
    assert listed[child["id"]]["accent"] == "#7CC4FA" and listed[parent["id"]] is None


def test_the_snapshot_wears_the_theme(store: Store) -> None:
    board = store.create_board("Look")
    store.add_card(board["id"], "note", text="hello")
    store.update_board(board["id"], theme="chrisx")
    page = Exporter(store).export_board(board["id"]).read_text()
    assert "--ivory:#000000" in page and "--slate:#F3ECDD" in page and "Fraunces" in page
    assert ".card{border-radius:0px}" in page and "<script" not in page
    store.update_board(board["id"], theme=None)
    assert "--ivory:#000000" not in Exporter(store).export_board(board["id"]).read_text()


def test_api_catalog_preview_and_mcp(client) -> None:
    names = [t["name"] for t in client.get("/api/themes").json()]
    assert names[0] == "vault" and "chrisx" in names and "film" in names
    preview = client.post("/api/themes/preview", headers=W,
                          json={"theme": {"preset": "custom", "ground": "#101010", "ink": "#fafafa", "accent": "#e0a33a"}})
    assert preview.json()["palette"]["scheme"] == "dark"
    assert client.post("/api/themes/preview", headers=W, json={"theme": "neon"}).status_code == 400
    m.set_client(client)
    try:
        m.create_board("Moodboard")
        assert "film theme" in m.set_board_theme("moodboard", preset="film")
        assert "custom theme" in m.set_board_theme("moodboard", ground="#0B1D13", ink="#E9F1E7", accent="#A9B470", font="serif")
        assert "theme: Custom" in m.read_board("moodboard")
        with pytest.raises(ValueError):
            m.set_board_theme("moodboard")
    finally:
        m.set_client(None)  # type: ignore[arg-type]


PROJECT = {
    "preset": "custom", "ground": "#0E0E0E", "ink": "#EDEBE6", "accent": "#B23A2E", "accent2": "#9A9893",
    "corners": "square", "grain": "print",
    "fonts": {"display": "Anton", "body": "Courier Prime"},
}


def test_a_project_theme_carries_fonts_grain_and_a_second_accent() -> None:
    pal = themes.palette(themes.normalize(PROJECT))
    assert pal["fontDisplay"].startswith('"Anton"') and "Impact" in pal["fontDisplay"]
    assert pal["font"].startswith('"Courier Prime"') and "monospace" in pal["font"]
    assert pal["fontsHref"] == "/fonts/css?family=Anton&family=Courier%20Prime"
    assert pal["grain"] == "print" and pal["accent2"] == "#9A9893"
    for bad in ({"fonts": {"display": "<script>"}}, {"grain": "glitter"}, {"backdrop": {"file": "../etc/passwd"}},
                {"backdrop": {"file": "a.jpg", "dim": 3}}, {"card": "teal"}):
        with pytest.raises(themes.ThemeError):
            themes.normalize({**PROJECT, **bad})
    # Its own card colour is used only if the text reads on it.
    assert themes.palette(themes.normalize({**PROJECT, "card": "#E9E9E9"}))["card"] != "#E9E9E9"
    assert themes.palette(themes.normalize({**PROJECT, "card": "#1B1B1B"}))["card"] == "#1B1B1B"


def test_boards_inside_wear_the_projects_theme(store: Store) -> None:
    album = store.create_board("Album")
    part = store.create_board("Part 1", parent_id=album["id"])
    song = store.create_board("Song", parent_id=part["id"])
    store.update_board(album["id"], theme="film")
    state = store.board_state(song["id"])
    assert state["board"]["theme"] is None and state["palette"]["accent"] == "#E8A04F" and state["theme_from"] == album["id"]
    store.update_board(part["id"], theme="midnight")  # a half of its own
    assert store.board_state(song["id"])["theme_from"] == part["id"]
    store.update_board(song["id"], theme="vault")      # the app's own look, on purpose, inside a themed project
    assert store.board_state(song["id"])["palette"] is None
    store.update_board(song["id"], theme=None)         # back to wearing the parent's
    assert store.board_state(song["id"])["palette"]["accent"] == "#7CC4FA"
    listed = {b["id"]: b["swatch"] for b in store.list_boards()}
    assert listed[song["id"]]["accent"] == "#7CC4FA"


def test_a_backdrop_is_an_uploaded_image(store: Store, tmp_path) -> None:
    board = store.create_board("Cover")
    with pytest.raises(Invalid, match="no uploaded image"):
        store.update_board(board["id"], theme={**PROJECT, "backdrop": {"file": "missing.jpg"}})
    store.config.uploads_dir.mkdir(parents=True, exist_ok=True)
    (store.config.uploads_dir / "cover.jpg").write_bytes(b"jpg")
    store.update_board(board["id"], theme={**PROJECT, "backdrop": {"file": "cover.jpg", "dim": 0.8, "tint": "#B23A2E", "tint_strength": 0.2}})
    pal = store.board_state(board["id"])["palette"]
    assert pal["backdrop"] == "/media/cover.jpg" and pal["backdropDim"] == "0.800"
    assert pal["backdropScrim"] == themes.mix("#0E0E0E", "#B23A2E", 0.2)
    page = Exporter(store).export_board(board["id"]).read_text()
    assert "http://127.0.0.1:4870/media/cover.jpg" in page and "http://127.0.0.1:4870/fonts/css?family=Anton" in page
    assert "<script" not in page


CSS = b"@font-face{font-family:'Anton';src:url(https://fonts.gstatic.com/s/anton/v25/abc.woff2) format('woff2')}"


def fake_google(seen: list):
    def fetch(url: str):
        seen.append(url)
        if "fonts.gstatic.com" in url:
            return 200, b"wOF2"
        if "family=Anton" in url and "ital" not in url:
            return 200, CSS
        return 400, b""
    return fetch


def test_fonts_are_fetched_once_and_served_locally(config) -> None:
    from fastapi.testclient import TestClient
    from cxboards.app import create_app
    seen: list = []
    with TestClient(create_app(config, font_fetch=fake_google(seen))) as c:
        board = c.post("/api/boards", json={"title": "Poster"}, headers=W).json()
        assert c.patch(f"/api/boards/{board['id']}", json={"theme": {**PROJECT, "fonts": {"display": "Anton"}}}, headers=W).status_code == 200
        css = c.get("/fonts/css", params={"family": "Anton"}).text
        assert "fonts.gstatic.com" not in css and "/fonts/file/" in css
        name = css.split("/fonts/file/")[1].split(")")[0]
        assert c.get(f"/fonts/file/{name}").content == b"wOF2"
        fetched = len(seen)
        c.get("/fonts/css", params={"family": "Anton"})
        assert len(seen) == fetched  # cached: Google isn't asked again
        refused = c.patch(f"/api/boards/{board['id']}", json={"theme": {**PROJECT, "fonts": {"display": "Not A Font"}}}, headers=W)
        assert refused.status_code == 400 and "no family called" in refused.json()["error"]
        assert c.get("/fonts/file/../../etc.woff2").status_code == 404


def test_animations_draw_in_the_theme_a_board_inherits(client) -> None:
    # An animation's colours (its guide, preview and exports) come from the theme the board wears,
    # which for a board inside a project is the project's.
    album = client.post("/api/boards", json={"title": "Album"}, headers=W).json()
    song = client.post("/api/boards", json={"title": "Song", "parent": album["id"]}, headers=W).json()
    client.patch(f"/api/boards/{album['id']}", json={"theme": "film"}, headers=W)
    guide = client.get("/api/motion/guide", params={"board": song["id"]}).text
    assert themes.palette({"preset": "film"})["canvas"] in guide
