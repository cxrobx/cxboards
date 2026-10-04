"""Ask: the chat panel's turn, run against a fake `claude` that speaks the CLI's stream-json,
so no subscription quota is spent. One real turn is run by hand (see CLAUDE.md)."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import socket
import stat
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn
from conftest import W
from fastapi.testclient import TestClient

from cxboards import chat as chatlib
from cxboards.app import create_app
from cxboards.config import Config

FAKE = r'''#!/usr/bin/env python3
import json, os, sys, time
record = os.environ["FAKE_CLAUDE_RECORD"]
mode = os.environ.get("FAKE_CLAUDE_MODE", "ok")
with open(record, "a") as f:
    f.write(json.dumps({"argv": sys.argv[1:], "cwd": os.getcwd(), "pid": os.getpid(),
                        "api_key": "ANTHROPIC_API_KEY" in os.environ}) + "\n")
def out(obj):
    print(json.dumps(obj), flush=True)
if mode == "fail":
    print("Invalid API key · Please run /login", file=sys.stderr, flush=True)
    sys.exit(1)
out({"type": "system", "subtype": "init", "tools": ["mcp__cxboards__add_cards"]})
out({"type": "stream_event", "event": {"type": "message_start"}})
out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Adding "}}})
if mode == "slow":
    time.sleep(30)
if mode == "pause":
    time.sleep(1.0)
out({"type": "stream_event", "event": {"type": "content_block_start", "index": 0,
     "content_block": {"type": "tool_use", "name": "ToolSearch"}}})
out({"type": "stream_event", "event": {"type": "content_block_stop", "index": 0}})
out({"type": "stream_event", "event": {"type": "content_block_start", "index": 1,
     "content_block": {"type": "tool_use", "name": "mcp__cxboards__add_cards"}}})
out({"type": "stream_event", "event": {"type": "content_block_stop", "index": 1}})
out({"type": "stream_event", "event": {"type": "message_start"}})
out({"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "two cards."}}})
out({"type": "result", "subtype": "success", "is_error": False, "result": "Adding\n\ntwo cards.",
     "total_cost_usd": 0.0123, "num_turns": 2})
'''


@pytest.fixture
def fake(tmp_path: Path, monkeypatch) -> Path:
    path = tmp_path / "claude"
    path.write_text(FAKE)
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    record = tmp_path / "calls.jsonl"
    monkeypatch.setenv("FAKE_CLAUDE_RECORD", str(record))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-never-reach-claude")
    return path


@pytest.fixture
def asking(config, fake):
    app = create_app(config, unfurl=lambda u: {}, export_delay=0.05, claude=lambda: str(fake))
    with TestClient(app) as client:
        yield client


def events(resp) -> list[tuple[str, dict]]:
    out = []
    for block in resp.text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.strip().splitlines() if ": " in line)
        if "event" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def calls(tmp_path: Path) -> list[dict]:
    return [json.loads(line) for line in (tmp_path / "calls.jsonl").read_text().splitlines()]


def test_a_turn_streams_and_is_kept(asking, tmp_path) -> None:
    board = asking.post("/api/boards", json={"title": "October sessions"}, headers=W).json()
    asking.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "Hook idea: half time"}, headers=W)
    resp = asking.post(f"/api/boards/{board['id']}/chat", json={"message": "Add two ideas"}, headers=W)
    got = events(resp)
    kinds = [k for k, _ in got]
    assert kinds[0] == "chat" and kinds[-1] == "done"
    assert "".join(d["text"] for k, d in got if k == "token") == "Adding \n\ntwo cards."
    assert [d["label"] for k, d in got if k == "tool"] == ["adding cards", "adding cards"]
    assert got[-1][1]["cost"] == 0.0123
    chat_id = got[0][1]["chat_id"]
    saved = asking.get(f"/api/chats/{chat_id}").json()
    assert [m["role"] for m in saved["messages"]] == ["user", "assistant"]
    assert saved["messages"][1]["tools"] == ["adding cards"] and saved["messages"][1]["cost"] == 0.0123
    assert asking.get(f"/api/boards/{board['id']}/chats").json()[0]["title"] == "Add two ideas"


def test_the_call_is_locked_down(asking, tmp_path, config) -> None:
    board = asking.post("/api/boards", json={"title": "B"}, headers=W).json()
    asking.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "a distinctive note"}, headers=W)
    asking.post(f"/api/boards/{board['id']}/chat", json={"message": "hi", "model": "opus"}, headers=W)
    call = calls(tmp_path)[0]
    argv = call["argv"]
    assert argv[0] == "-p" and argv[1] == "hi"
    flag = lambda name: argv[argv.index(name) + 1]  # noqa: E731
    assert flag("--model") == "opus"
    assert flag("--permission-mode") == "dontAsk"
    assert flag("--setting-sources") == "project"
    assert "--strict-mcp-config" in argv
    allowed = argv[argv.index("--allowedTools") + 1: argv.index("--disallowedTools")]
    assert "mcp__cxboards" in allowed and "Bash" not in allowed
    assert {"Bash", "Edit", "Write"} <= set(argv[argv.index("--disallowedTools") + 1: argv.index("--append-system-prompt")])
    system = flag("--append-system-prompt")
    assert "assistant inside CXBoards" in system and "a distinctive note" in system
    mcp = json.loads(Path(flag("--mcp-config")).read_text())
    assert list(mcp["mcpServers"]) == ["cxboards"] and mcp["mcpServers"]["cxboards"]["args"] == ["mcp"]
    assert not call["cwd"].startswith(str(Path.home()))  # no ~/CLAUDE.md reload
    assert call["api_key"] is False  # the subscription, not the API


def test_history_and_selection_travel_with_the_question(asking, tmp_path) -> None:
    board = asking.post("/api/boards", json={"title": "B"}, headers=W).json()
    card = asking.post(f"/api/boards/{board['id']}/cards", json={"kind": "note", "text": "the bridge"}, headers=W).json()
    first = events(asking.post(f"/api/boards/{board['id']}/chat", json={"message": "first question"}, headers=W))
    chat_id = first[0][1]["chat_id"]
    asking.post(f"/api/boards/{board['id']}/chat",
                json={"message": "and this one?", "chat_id": chat_id, "selection": [card["id"]]}, headers=W)
    second = calls(tmp_path)[1]["argv"]
    prompt = second[1]
    assert "Chris: first question" in prompt and "You: Adding" in prompt and prompt.endswith("Chris now asks: and this one?")
    system = second[second.index("--append-system-prompt") + 1]
    assert "Cards Chris has selected" in system and card["id"] in system.split("selected")[1]


def test_a_failed_turn_says_why(config, fake, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "fail")
    app = create_app(config, unfurl=lambda u: {}, claude=lambda: str(fake))
    with TestClient(app) as client:
        board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
        got = events(client.post(f"/api/boards/{board['id']}/chat", json={"message": "hi"}, headers=W))
        assert got[-1][0] == "error" and "Please run /login" in got[-1][1]["message"]
        saved = client.get(f"/api/chats/{got[0][1]['chat_id']}").json()
        assert "Please run /login" in saved["messages"][1]["error"]


def test_no_claude_installed(config) -> None:
    app = create_app(config, unfurl=lambda u: {}, claude=lambda: None)
    with TestClient(app) as client:
        assert client.get("/api/chat/info").json()["available"] is False
        board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
        got = events(client.post(f"/api/boards/{board['id']}/chat", json={"message": "hi"}, headers=W))
        assert got[-1][0] == "error" and "isn't installed" in got[-1][1]["message"]


def test_stopping_kills_the_process(fake, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")

    async def first_token_then_stop() -> None:
        gen = chatlib.run_turn([str(fake), "-p", "x"])
        first = await gen.__anext__()
        assert first == {"event": "token", "text": "Adding "}
        await gen.aclose()

    asyncio.run(first_token_then_stop())
    pid = calls(tmp_path)[0]["pid"]
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_chats_can_be_deleted(asking) -> None:
    board = asking.post("/api/boards", json={"title": "B"}, headers=W).json()
    chat_id = events(asking.post(f"/api/boards/{board['id']}/chat", json={"message": "hi"}, headers=W))[0][1]["chat_id"]
    assert asking.delete(f"/api/chats/{chat_id}", headers=W).status_code == 200
    assert asking.get(f"/api/boards/{board['id']}/chats").json() == []



@contextlib.contextmanager
def served(tmp_path: Path, fake: Path):
    """The app on a real uvicorn server: TestClient buffers a whole response before returning
    any of it, so it can't leave a turn halfway the way a closing panel does."""
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    app = create_app(Config(home=tmp_path / "home", port=port), unfurl=lambda u: {}, claude=lambda: str(fake))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.02)
    try:
        with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30) as client:
            yield app, client
    finally:
        server.should_exit = True
        thread.join(15)


def watch_until_first_token(client, board_id: str, message: str) -> str:
    """Start a turn, read until its first words, then go away (Chris opening another board)."""
    with client.stream("POST", f"/api/boards/{board_id}/chat", json={"message": message}, headers=W) as resp:
        seen = ""
        for chunk in resp.iter_text():
            seen += chunk
            if "event: token" in seen:
                break
    return json.loads(seen.split("event: chat\ndata: ", 1)[1].split("\n", 1)[0])["chat_id"]


def wait_until_idle(client, chat_id: str) -> dict:
    for _ in range(100):
        chat = client.get(f"/api/chats/{chat_id}").json()
        if not chat["running"]:
            return chat
        time.sleep(0.1)
    raise AssertionError("the turn never finished")


def test_a_turn_keeps_going_when_nobody_is_watching(fake, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "pause")
    with served(tmp_path, fake) as (app, client):
        board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
        chat_id = watch_until_first_token(client, board["id"], "add some animations")

        assert client.get(f"/api/chats/{chat_id}").json()["running"] is True
        assert client.get(f"/api/boards/{board['id']}/chats").json()[0]["running"] is True
        again = client.post(f"/api/boards/{board['id']}/chat", json={"message": "and?", "chat_id": chat_id}, headers=W)
        assert again.status_code == 400  # one turn per chat at a time

        # Coming back: the watcher gets the whole turn from the start, then its end.
        got = events(client.get(f"/api/chats/{chat_id}/live"))
        assert [k for k, _ in got][0] == "chat" and got[-1][0] == "done"
        assert "".join(d["text"] for k, d in got if k == "token") == "Adding \n\ntwo cards."

        chat = wait_until_idle(client, chat_id)
        assert chat["messages"][-1]["text"] == "Adding \n\ntwo cards." and "stopped" not in chat["messages"][-1]
        assert events(client.get(f"/api/chats/{chat_id}/live")) == []  # nothing running now


def test_stop_ends_a_running_turn_and_kills_claude(fake, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    with served(tmp_path, fake) as (app, client):
        board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
        chat_id = watch_until_first_token(client, board["id"], "slow one")
        assert client.delete(f"/api/chats/{chat_id}", headers=W).status_code == 400  # not mid-answer

        assert client.post(f"/api/chats/{chat_id}/stop", headers=W).json() == {"ok": True}
        chat = wait_until_idle(client, chat_id)
        last = chat["messages"][-1]
        assert last["stopped"] is True and last["text"] == "Adding"
        assert client.post(f"/api/chats/{chat_id}/stop", headers=W).json() == {"ok": False}
    time.sleep(0.2)
    with pytest.raises(ProcessLookupError):
        os.kill(calls(tmp_path)[0]["pid"], 0)


def test_shutting_down_stops_running_turns(fake, monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FAKE_CLAUDE_MODE", "slow")
    with served(tmp_path, fake) as (app, client):
        board = client.post("/api/boards", json={"title": "B"}, headers=W).json()
        chat_id = watch_until_first_token(client, board["id"], "slow one")
    assert app.state.store.chat(chat_id)["messages"][-1]["stopped"] is True
