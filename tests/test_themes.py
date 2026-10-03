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
    assert themes.normalize("vault") is None and themes.normalize(None) is None
    assert themes.palette(None) is None


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
