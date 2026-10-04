"""The template library (templates/, src/cxboards/templates.py): every file builds, nothing is in it twice."""

from __future__ import annotations

from pathlib import Path

import pytest

from cxboards import mcp_server as m
from cxboards import templates as lib
from cxboards.store import Store

from conftest import AGENT, W
from test_store import assert_no_overlaps

LIBRARY = lib.load()


def test_the_library_loads_with_every_template_once() -> None:
    # load() refuses a slug, a name or a source used twice, so reaching here is the no-duplicates check.
    assert LIBRARY.templates, "the library is empty"
    assert {c["slug"] for c in LIBRARY.categories} >= {t.category for t in LIBRARY.templates.values()}
    assert len({t.name.lower() for t in LIBRARY.templates.values()}) == len(LIBRARY.templates)


def _boards_under(store: Store, board_id: str) -> list[str]:
    out = [board_id]
    for card in store.cards(board_id):
        if card["kind"] == "board" and not card["data"].get("shortcut"):
            out += _boards_under(store, card["data"]["board_id"])
    return out


def _expected_cards(cards: list) -> int:
    n = lib.count_cards(cards)
    for card in cards:
        if card != "break" and "board" in card:
            n += _expected_cards(card.get("cards") or [])
    return n


@pytest.mark.parametrize("slug", sorted(LIBRARY.templates))
def test_every_template_builds_as_one_step_without_overlaps(store: Store, slug: str) -> None:
    t = LIBRARY.templates[slug]
    events = []
    store.listeners.append(lambda *e: events.append(e))
    board = store.build_board(t.name, lib.plan(t.cards), theme=t.theme)

    boards = _boards_under(store, board["id"])
    for b in boards:
        assert_no_overlaps(store, b)
    assert sum(len(store.cards(b)) for b in boards) == _expected_cards(t.cards)
    assert len({e[4] for e in events}) == 1  # one history entry: one undo step
    assert (store.board(board["id"])["theme"] or {}).get("preset") == t.theme


def write(root: Path, rel: str, text: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


GOOD = "name: {name}\nuse_when: Testing.\ncards:\n  - note: Hello\n"


@pytest.mark.parametrize(
    "files, message",
    [
        ({"a/one.yaml": GOOD.format(name="One"), "b/one.yaml": GOOD.format(name="Other")}, "already a/one.yaml"),
        ({"a/one.yaml": GOOD.format(name="Same"), "b/two.yaml": GOOD.format(name="same")}, "name 'same' is already used"),
        (
            {
                "a/one.yaml": GOOD.format(name="One") + "source: https://x.com/t\n",
                "b/two.yaml": GOOD.format(name="Two") + "source: https://x.com/t/\n",
            },
            "already the source",
        ),
        ({"a/one.yaml": GOOD.format(name="One") + "colour: red\n"}, "unknown keys colour"),
        ({"a/one.yaml": "name: One\nuse_when: x\ncards:\n  - column: A\n    cards:\n      - column: B\n"}, "a column holds"),
        ({"a/one.yaml": "name: One\nuse_when: x\ncards:\n  - note: Hi\n    color: red\n"}, "color is one of"),
        ({"a/one.yaml": "name: One\nuse_when: x\ncards:\n  - todo: T\n"}, "a to-do needs items"),
        ({"a/one.yaml": GOOD.format(name="One") + "also: [nowhere]\n"}, "isn't another category"),
        ({"c/one.yaml": GOOD.format(name="One")}, "not a category"),
        ({"a/One.yaml": GOOD.format(name="One")}, "lowercase-with-dashes"),
        ({"a/one.yaml": "name: One\nuse_when: x\ncards:\n  - todo: T\n    items: ['*bold* step']\n"}, "plain text"),
    ],
)
def test_format_mistakes_name_the_file_and_the_problem(tmp_path: Path, files: dict, message: str) -> None:
    write(tmp_path, "categories.yaml", "- {slug: a, name: A}\n- {slug: b, name: B}\n")
    for rel, text in files.items():
        write(tmp_path, rel, text)
    with pytest.raises(lib.TemplateError, match=message):
        lib.load(tmp_path)


def test_rows_break_and_wrap() -> None:
    cards = [{"note": "a"}, "break"] + [{"column": f"C{i}", "cards": [{"note": "x"}]} for i in range(7)]
    placed = lib.plan(cards)
    assert placed[0]["y"] < placed[1]["y"]  # the break started a new row
    rows = sorted({p["y"] for p in placed[1:]})
    assert len(rows) == 2  # seven 300 px columns don't fit one 1800 px row


def test_search_puts_name_matches_first() -> None:
    hits = lib.search(LIBRARY, "session plan")
    assert hits and hits[0].slug == "studio-session-plan"
    assert all(t.category == "music" or "music" in t.also for t in lib.search(LIBRARY, category="music"))
    assert lib.search(LIBRARY, "zzzz-nothing") == []
    # Filler words don't count, and "mood board" finds the moodboards.
    assert lib.search(LIBRARY, "a mood board for my wedding")[0].slug == "wedding-moodboard"
    assert lib.search(LIBRARY, "podcast outline")[0].slug == "podcast-outline"


def test_the_readme_index_is_current() -> None:
    import subprocess
    import sys

    root = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "scripts/template-index.py", "--check"], cwd=root, capture_output=True, text=True)
    assert done.returncode == 0, done.stdout


def test_api_lists_and_builds_from_the_library(client) -> None:
    lib_json = client.get("/api/templates").json()
    music = next(c for c in lib_json["categories"] if c["slug"] == "music")
    assert music["count"] >= 1 and music["name"] == "Music"
    found = client.get("/api/templates", params={"q": "mix notes"}).json()["templates"]
    assert found[0]["slug"] == "mix-revision-notes" and found[0]["preview"]
    assert client.get("/api/templates/nope").status_code == 404

    made = client.post("/api/boards", json={"title": "", "template": "single-rollout"}, headers=W).json()
    assert made["title"] == "Single rollout plan"
    state = client.get(f"/api/boards/{made['id']}").json()
    assert len(state["cards"]) == lib.count_cards(LIBRARY.templates["single-rollout"].cards)

    folder = client.post("/api/boards", json={"title": "Sessions"}, headers=W).json()
    inside = client.post(
        "/api/boards", json={"title": "Oct 4", "template": "studio-session-plan", "parent": folder["id"]}, headers=AGENT
    ).json()
    assert inside["parent_id"] == folder["id"] and inside["theme"] == {"preset": "studio"}


def test_agents_find_and_use_templates(client) -> None:
    m.set_client(client)
    try:
        overview = m.list_templates()
        assert "categories" in overview and "- music · Music" in overview
        assert "studio-session-plan" in m.list_templates(category="music")
        assert m.list_templates(query="beat pack").startswith("- beat-pack")
        assert "Created Beat pack" in m.create_board("", template="beat-pack")
        assert "Beat pack" in m.list_boards()
    finally:
        m.set_client(None)  # type: ignore[arg-type]


def test_the_app_leaves_a_broken_file_out_and_says_so(tmp_path: Path) -> None:
    write(tmp_path, "categories.yaml", "- {slug: a, name: A}\n")
    write(tmp_path, "a/good.yaml", GOOD.format(name="Good"))
    write(tmp_path, "a/typo.yaml", "name: Typo\nuse_when: x\ncards:\n  - todo: T\n    items: [a, b?, c: d]\n")
    write(tmp_path, "a/twin.yaml", GOOD.format(name="good"))
    cat = lib.catalog(tmp_path)
    assert list(cat.templates) == ["good"]
    assert len(cat.problems) == 2 and any("twin.yaml" in p for p in cat.problems)
    with pytest.raises(lib.TemplateError):
        lib.load(tmp_path)  # the tests stay strict
