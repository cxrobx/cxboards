"""The store's invariants (see the docstring at the top of store.py)."""

from __future__ import annotations

import itertools
import os

import pytest

from cxboards.layout import Rect
from cxboards.store import Invalid, NotFound, Store


def canvas_rects(store: Store, board_id: str) -> dict[str, Rect]:
    return {
        c["id"]: Rect(c["x"], c["y"], c["w"], c["h"])
        for c in store.cards(board_id)
        if not c["column_id"]
    }


def assert_no_overlaps(store: Store, board_id: str) -> None:
    rects = canvas_rects(store, board_id)
    for (a, ra), (b, rb) in itertools.combinations(rects.items(), 2):
        assert not ra.overlaps(rb, gap=0), f"{a} overlaps {b}: {ra} {rb}"


def test_auto_placement_never_overlaps(store: Store) -> None:
    board = store.create_board("Sessions")
    for i in range(40):
        store.add_card(board["id"], "note", text="x" * (i * 13 % 300), actor="agent")
    assert_no_overlaps(store, board["id"])


def test_near_placement_never_overlaps_and_sits_beside(store: Store) -> None:
    board = store.create_board("Sessions")
    anchor = store.add_card(board["id"], "note", text="anchor")
    for _ in range(6):
        store.add_card(board["id"], "note", text="next", near=anchor["id"], actor="agent")
    for _ in range(4):
        store.add_card(board["id"], "note", text="below", near=anchor["id"], side="below", actor="agent")
    assert_no_overlaps(store, board["id"])
    first = [c for c in store.cards(board["id"]) if c["text"] == "next"][0]
    assert first["x"] > anchor["x"] and first["y"] == anchor["y"]


def test_batch_bumps_rev_once_and_emits_once(store: Store) -> None:
    board = store.create_board("Sessions")
    events = []
    store.listeners.append(lambda *e: events.append(e))
    before = store.board(board["id"])["rev"]
    store.add_cards(board["id"], [{"kind": "note", "text": str(i)} for i in range(5)])
    assert store.board(board["id"])["rev"] == before + 1
    assert len(events) == 1 and len(events[0][2]) == 5 and events[0][3] == "agent"


def test_failed_write_rolls_back_whole_batch(store: Store) -> None:
    board = store.create_board("Sessions")
    with pytest.raises(Invalid):
        store.add_cards(board["id"], [{"kind": "note", "text": "ok"}, {"kind": "link", "data": {"url": "nope"}}])
    assert store.cards(board["id"]) == []


def test_columns_hold_cards_in_order_and_grow(store: Store) -> None:
    board = store.create_board("Sessions")
    column = store.add_card(board["id"], "column", text="Session 1")
    a = store.add_card(board["id"], "note", text="a", column_id=column["id"])
    b = store.add_card(board["id"], "note", text="b", column_id=column["id"])
    c = store.add_card(board["id"], "note", text="c", column_id=column["id"], index=0)
    kids = sorted((k for k in store.cards(board["id"]) if k["column_id"] == column["id"]), key=lambda k: k["position"])
    assert [k["id"] for k in kids] == [c["id"], a["id"], b["id"]]
    assert store.card(column["id"])["h"] > column["h"]


def test_deleting_a_column_returns_its_cards_to_the_canvas(store: Store) -> None:
    board = store.create_board("Sessions")
    column = store.add_card(board["id"], "column", text="Session 1")
    kids = [store.add_card(board["id"], "note", text=str(i), column_id=column["id"]) for i in range(3)]
    store.add_card(board["id"], "note", text="outside")
    store.delete_card(column["id"])
    cards = {c["id"]: c for c in store.cards(board["id"])}
    assert all(cards[k["id"]]["column_id"] is None for k in kids)
    assert len(cards) == 4
    assert_no_overlaps(store, board["id"])


def test_deleting_a_board_card_keeps_the_board(store: Store) -> None:
    parent = store.create_board("Year plan")
    child = store.create_board("October", parent_id=parent["id"])
    store.add_card(child["id"], "note", text="keep me")
    board_card = [c for c in store.cards(parent["id"]) if c["kind"] == "board"][0]
    store.delete_card(board_card["id"])
    assert store.board(child["id"])["parent_id"] is None
    assert len(store.cards(child["id"])) == 1


def test_group_into_column_keeps_reading_order_and_clears_space(store: Store) -> None:
    board = store.create_board("Sessions")
    notes = [store.add_card(board["id"], "note", text=f"n{i}") for i in range(4)]
    column = store.group_into_column(board["id"], [n["id"] for n in reversed(notes)], "Grouped", actor="agent")
    kids = sorted((k for k in store.cards(board["id"]) if k["column_id"] == column["id"]), key=lambda k: k["position"])
    assert [k["text"] for k in kids] == ["n0", "n1", "n2", "n3"]
    assert_no_overlaps(store, board["id"])


def test_make_sub_board_moves_cards_and_leaves_a_board_card(store: Store) -> None:
    board = store.create_board("Year plan")
    column = store.add_card(board["id"], "column", text="Refs")
    store.add_card(board["id"], "note", text="inside", column_id=column["id"])
    loose = store.add_card(board["id"], "note", text="loose")
    stay = store.add_card(board["id"], "note", text="stay")
    card = store.make_sub_board(board["id"], [column["id"], loose["id"]], "October", actor="agent")
    child_id = card["data"]["board_id"]
    assert store.board(child_id)["parent_id"] == board["id"]
    assert {c["text"] for c in store.cards(child_id)} == {"Refs", "inside", "loose"}
    assert {c["id"] for c in store.cards(board["id"])} == {stay["id"], card["id"]}
    assert [b["title"] for b in store.breadcrumbs(child_id)] == ["Year plan", "October"]


def test_arrange_grid_never_overlaps(store: Store) -> None:
    board = store.create_board("Sessions")
    ids = [store.add_card(board["id"], "note", text="y" * (i * 40), x=i * 7, y=i * 5)["id"] for i in range(9)]
    store.add_card(board["id"], "note", text="bystander", x=300, y=300)
    store.arrange(board["id"], ids, "grid", actor="agent")
    assert_no_overlaps(store, board["id"])


def test_audio_is_only_read(store: Store, bounce) -> None:
    board = store.create_board("Sessions")
    before = (bounce.stat().st_mtime_ns, bounce.read_bytes())
    card = store.add_card(board["id"], "audio", data={"path": str(bounce)}, text="v2 bounce")
    assert card["data"]["name"] == "endofworld_2.wav"
    assert (bounce.stat().st_mtime_ns, bounce.read_bytes()) == before
    with pytest.raises(Invalid):
        store.add_card(board["id"], "audio", data={"path": str(bounce.with_suffix(".flp"))})
    with pytest.raises(Invalid):
        store.add_card(board["id"], "audio", data={"path": "relative/song.mp3"})


def test_store_writes_only_inside_its_home(store: Store, tmp_path) -> None:
    home = store.config.home.resolve()
    board = store.create_board("Sessions")
    store.add_card(board["id"], "note", text="hello")
    for root, _dirs, files in os.walk(tmp_path):
        for name in files:
            path = os.path.realpath(os.path.join(root, name))
            assert path.startswith(str(home)) or "MuZik" in path, path


def test_resolve_board_by_title(store: Store) -> None:
    a = store.create_board("October sessions")
    store.create_board("November sessions")
    assert store.resolve_board("october")["id"] == a["id"]
    assert store.resolve_board(a["id"])["id"] == a["id"]
    with pytest.raises(Invalid):
        store.resolve_board("sessions")
    with pytest.raises(NotFound):
        store.resolve_board("december")


def test_board_cannot_move_inside_itself(store: Store) -> None:
    parent = store.create_board("Year")
    child = store.create_board("October", parent_id=parent["id"])
    board_card = [c for c in store.cards(parent["id"]) if c["kind"] == "board"][0]
    with pytest.raises(Invalid):
        store.move_card(board_card["id"], board_id=child["id"])


def test_about_here_placement_avoids_covering_cards(store: Store) -> None:
    board = store.create_board("Sessions")
    big = store.add_card(board["id"], "note", text="x" * 400, x=100, y=100)
    card = store.add_card(board["id"], "note", text="new", x=120, y=120, avoid=True)
    assert_no_overlaps(store, board["id"])
    assert abs(card["x"] - 120) + abs(card["y"] - 120) < 900  # still near where it was asked for
    exact = store.add_card(board["id"], "note", text="exact", x=130, y=130)
    assert (exact["x"], exact["y"]) == (130, 130)  # a pointer drop keeps its spot
