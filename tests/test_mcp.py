"""The MCP tools, driven against the real app through a TestClient."""

from __future__ import annotations

import pytest

from cxboards import mcp_server as m


@pytest.fixture(autouse=True)
def wired(client):
    m.set_client(client)
    yield
    m.set_client(None)  # type: ignore[arg-type]


def test_agent_plans_a_session_end_to_end(client, bounce) -> None:
    assert "No boards yet" in m.list_boards()
    assert "Created October sessions" in m.create_board("October sessions", "Planning the month")
    added = m.add_cards(
        "october",
        [
            {"kind": "note", "text": "Goal: the hook opens up; vocal stays close"},
            {"kind": "audio", "path": str(bounce), "text": "last bounce"},
            {"kind": "column", "title": "Session 1", "cards": [{"kind": "todo", "title": "Prep", "items": ["bounce v2"]}]},
        ],
    )
    assert added.count("\n- ") == 4
    outline = m.read_board("october")
    ids = [line.split()[2].rstrip("]") for line in outline.splitlines() if line.startswith("- [")]
    assert len(ids) == 2  # note + audio on the canvas; the column is a heading
    assert "Session 1" in outline and "[ ] bounce v2" in outline

    grouped = m.group_into_column("october", ids, "Session 0")
    assert "Grouped 2 cards" in grouped
    assert "## column" in m.read_board("october")

    m.add_cards("october", [{"kind": "note", "text": "Try: pull the drums out of the pre"}], column="Session 1")
    assert "pull the drums" in m.read_board("october").split("Session 1")[1]

    note_id = ids[0]
    assert "Moved" in m.move_card(note_id, out_of_column=True)
    made = m.make_sub_board("october", [note_id], "Hook ideas")
    assert "Made board Hook ideas" in made
    assert "inside October sessions" in m.list_boards()
    assert "Artifacts/Muzik/Boards/october-sessions" in m.snapshot_board("october")


def test_errors_read_as_sentences(client) -> None:
    with pytest.raises(ValueError, match="no board"):
        m.read_board("nowhere")
    m.create_board("A board")
    with pytest.raises(ValueError, match="say where"):
        m.move_card("c_123")
