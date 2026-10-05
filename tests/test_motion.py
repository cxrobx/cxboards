"""Animation cards (motion.py, motion/): drawing code checked before it's saved, played in a sandbox,
rendered on the server for previews, posters and video, and never a script in a snapshot."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from cxboards import mcp_server as m
from cxboards import motion as motionlib
from cxboards.export import Exporter
from cxboards.outline import board_outline
from cxboards.store import Invalid, Store

from conftest import AGENT, PNG_1PX, W

needs_node = pytest.mark.skipif(not motionlib.available(), reason="Node and motion/node_modules aren't installed")

INK = """
function draw({ pen, w, h, p, TAU }) {
  pen.paper()
  pen.circle(w / 2, h / 2, 20 + 10 * Math.sin(TAU * p))
}
"""
OVER = """
function draw({ pen, w, h, p, cover }) {
  cover()
  pen.cloud(((p + 0.2) % 1) * w, h * 0.3, 30, { seed: 2 })
}
"""


def test_the_store_keeps_motion_tidy(store: Store, tmp_path: Path) -> None:
    board = store.create_board("Moves")
    with pytest.raises(Invalid, match="needs motion"):
        store.add_card(board["id"], "animation", data={})
    with pytest.raises(Invalid, match="needs code"):
        store.add_card(board["id"], "animation", data={"motion": {"code": "  "}})
    card = store.add_card(board["id"], "animation", data={"motion": {"code": INK, "loop": 500}, "aspect": 9})
    assert card["data"]["motion"]["loop"] == 60 and card["data"]["aspect"] == 3
    assert card["h"] > card["w"] * 2  # tall card, tall estimate
    image = tmp_path / "pic.png"
    image.write_bytes(PNG_1PX)
    pic = store.add_card(board["id"], "image", data={"file": store.import_image_path(str(image))})
    moving = store.update_card(pic["id"], data={"motion": {"code": OVER, "poster": "../../etc/passwd"}})
    assert moving["data"]["motion"] == {"code": OVER, "loop": 6}  # a poster must be one of its uploads
    still = store.update_card(pic["id"], data={"motion": None})
    assert "motion" not in still["data"]
    outline = board_outline(store, board["id"], "http://x")
    assert "[animation " in outline and "(60s loop)" in outline


@needs_node
def test_broken_code_is_refused_before_it_reaches_the_board(client) -> None:
    board = client.post("/api/boards", json={"title": "Moves"}, headers=W).json()
    typo = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "animation", "code": "function draw({pen}) { pen.lien(0,0,1,1) }"}, headers=AGENT)
    assert typo.status_code == 400 and "pen.lien is not a function" in typo.json()["error"]
    nodraw = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "animation", "code": "const x = 1"}, headers=AGENT)
    assert "needs a function draw" in nodraw.json()["error"]
    assert client.get(f"/api/boards/{board['id']}").json()["cards"] == []


@needs_node
def test_the_guides_examples_run_and_helpers_are_plain_names(client) -> None:
    board = client.post("/api/boards", json={"title": "Moves"}, headers=W).json()
    # TAU used bare at the top of setup, as the guide's dandelion does (it failed before).
    bare = "const k = TAU / 4\nfunction setup({ w }) { return { r: lerp(10, 20, 0.5) + k } }\nfunction draw({ pen, state }) { pen.paper(); pen.dot(10, 10, clamp(state.r, 1, 3)) }"
    assert client.post(f"/api/boards/{board['id']}/cards", json={"kind": "animation", "code": bare}, headers=AGENT).status_code == 200
    for example in motionlib.GUIDE.split("    function setup")[1:2]:
        code = "function setup" + example.split("\nExample, over an image card")[0]
        code = "\n".join(line[4:] if line.startswith("    ") else line for line in code.splitlines())
        made = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "animation", "code": code}, headers=AGENT)
        assert made.status_code == 200, made.json()


@needs_node
def test_an_endless_loop_is_stopped(client, monkeypatch) -> None:
    monkeypatch.setattr(motionlib, "CHECK_SECONDS", 2)
    board = client.post("/api/boards", json={"title": "Moves"}, headers=W).json()
    spin = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "animation", "code": "function draw() { while (true) {} }"}, headers=AGENT)
    assert spin.status_code == 400 and "Stopped" in spin.json()["error"]


@needs_node
def test_animations_play_preview_and_post_a_still(client, tmp_path: Path) -> None:
    board = client.post("/api/boards", json={"title": "Moves"}, headers=W).json()
    card = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "animation", "code": INK, "loop": 4, "text": "breathing"}, headers=AGENT).json()
    assert card["data"]["motion"]["loop"] == 4

    sheet = client.get(f"/api/cards/{card['id']}/motion/preview")
    assert sheet.status_code == 200 and sheet.content[:4] == b"\x89PNG"

    for _ in range(50):  # the poster is made in the background
        motion = client.get(f"/api/cards/{card['id']}").json()["data"]["motion"]
        if motion.get("poster"):
            break
        time.sleep(0.1)
    assert motion.get("poster"), "no poster frame"

    gif = client.get(f"/api/cards/{card['id']}/motion/export.gif")
    assert gif.status_code == 200 and gif.content[:3] == b"GIF"


@needs_node
def test_an_image_comes_to_life_and_goes_still_again(client, tmp_path: Path) -> None:
    board = client.post("/api/boards", json={"title": "Cover"}, headers=W).json()
    image = tmp_path / "cover.png"
    image.write_bytes(PNG_1PX)
    pic = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "image", "path": str(image), "text": "cover"}, headers=W).json()
    bad = client.post(f"/api/cards/{pic['id']}/motion", json={"code": "function draw() { nope() }"}, headers=AGENT)
    assert bad.status_code == 400 and "nope is not defined" in bad.json()["error"]
    moving = client.post(f"/api/cards/{pic['id']}/motion", json={"code": OVER, "loop": 8}, headers=AGENT).json()
    assert moving["data"]["motion"]["loop"] == 8 and moving["data"]["file"] == pic["data"]["file"]
    client.post(f"/api/cards/{pic['id']}/motion/error", json={"message": "TypeError: x"}, headers=W)
    assert "ANIMATION ERROR: TypeError: x" in client.get(f"/api/boards/{board['id']}/outline").text
    still = client.post(f"/api/cards/{pic['id']}/motion", json={"code": ""}, headers=W).json()
    assert "motion" not in still["data"]
    note = client.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "x"}, headers=W).json()
    assert client.post(f"/api/cards/{note['id']}/motion", json={"code": INK}, headers=W).status_code == 400


def test_the_sandbox_page_can_only_draw(client) -> None:
    page = client.get("/motion/runner")
    csp = page.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "connect-src" not in csp  # nothing may load or connect
    assert "/*RUNTIME*/" not in page.text and "CXMotion" in page.text


def test_a_snapshot_shows_a_still_never_a_script(store: Store) -> None:
    board = store.create_board("Moves")
    store.add_card(board["id"], "animation", text="breathing", data={"motion": {"code": INK + "\n// </script><script>alert(1)</script>"}})
    store.update_board(board["id"], in_onyx=True)
    page = Exporter(store).export_board(board["id"]).read_text()
    assert "<script" not in page and "moves in CXBoards" in page


@needs_node
def test_agents_read_the_guide_make_one_and_look_at_it(client) -> None:
    m.set_client(client)
    try:
        m.create_board("Night drive")
        guide = m.motion_guide("Night drive")
        assert "Ask first" in guide and "ONE short message" in guide and "env.palette here" in guide
        assert "Added" in m.add_cards("Night drive", [{"kind": "animation", "code": INK, "text": "headlights"}])
        state = client.get("/api/boards/Night drive").json()
        card_id = next(c["id"] for c in state["cards"] if c["kind"] == "animation")
        assert "Animated" in m.animate(card_id, INK.replace("20 +", "24 +"), loop=5)
        assert "5s loop" in m.animation_code(card_id)
        # Through the MCP layer, as an agent calls it (the function alone hid a serialization bug).
        import asyncio
        import base64

        content = asyncio.run(m.mcp.call_tool("preview_animation", {"card_id": card_id}))
        blocks = content[0] if isinstance(content, tuple) else content
        image = next(b for b in blocks if getattr(b, "type", "") == "image")
        assert base64.b64decode(image.data)[:4] == b"\x89PNG"
    finally:
        m.set_client(None)  # type: ignore[arg-type]
