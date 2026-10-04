"""Ask: a chat about the open board, answered by Claude on Chris's subscription.

Each turn is one headless ``claude -p`` call (the bare binary, never the shell
function, which adds --dangerously-skip-permissions). The agent gets:

* only the ``cxboards`` MCP (``--mcp-config`` + ``--strict-mcp-config``), so it can
  read and change boards, and its changes land live, glowing, with an Undo;
* Read/Grep/Glob and web search/fetch; shell and file edits are refused without
  asking (``--permission-mode dontAsk``);
* no user settings (``--setting-sources project``): Chris's hooks (the finish
  ding, prompt injectors) don't fire for a chat turn;
* a working directory outside the home folder, so the 41k-token ~/CLAUDE.md isn't
  reloaded on every call. A short brief plus the board's outline replace it.

Turns are stateless, as in Onyx: earlier turns travel in the prompt as a
transcript, and the board is read fresh every time.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, AsyncIterator

MODELS = {"sonnet": "Sonnet", "opus": "Opus", "haiku": "Haiku"}
DEFAULT_MODEL = "sonnet"
FIRST_ACTIVITY_TIMEOUT = 90.0
TURN_TIMEOUT = 600.0
HISTORY_TURNS = 12
# Claude Code's own plumbing (loading deferred tools): not something Chris needs to watch.
QUIET_TOOLS = {"ToolSearch"}

ALLOWED_TOOLS = ["mcp__cxboards", "Read", "Grep", "Glob", "WebSearch", "WebFetch"]
DISALLOWED_TOOLS = ["Bash", "Edit", "Write", "NotebookEdit", "Task"]

TOOL_LABELS = {
    "read_board": "reading the board",
    "list_boards": "looking through boards",
    "search": "searching",
    "add_cards": "adding cards",
    "update_card": "editing a card",
    "move_card": "moving a card",
    "delete_card": "removing a card",
    "duplicate_cards": "duplicating",
    "connect_cards": "drawing a line",
    "label_cards": "labelling",
    "arrange": "tidying up",
    "group_into_column": "grouping into a column",
    "make_sub_board": "making a board",
    "create_board": "making a board",
    "export_board": "exporting",
    "WebSearch": "searching the web",
    "WebFetch": "reading a page",
    "Read": "reading a file",
    "Grep": "searching files",
    "Glob": "looking for files",
}

BRIEF = """You are the assistant inside CXBoards, Chris's own visual planning board (Milanote-like, local,
single user). Chris Robinson is a producer and artist (Chris X): he makes music every month in FL
Studio, and plans studio sessions on these boards. His Studio Coach rules: say the song's goal in
one sentence; a reference is optional; feeling first (what the song is about, how each section
should feel); suggestions are offered, never "fix this", and he decides by ear.

You can read and change boards with the cxboards tools; your changes appear live on his screen,
highlighted, and he can undo any of your steps with one click. Work like this:
- The current board's outline is below; read_board again only if you need fresher detail.
- Place cards with `column` or `near`, never coordinates; put loose suggestions in a column.
- Ask before deleting cards or moving more than a handful; never delete a board.
- Animations (motion graphics, a moving cover, "bring this picture to life", an animated drawing):
  call motion_guide with this board first and follow it. Unless his request already settles them,
  ask your clarifying questions in one short message, with your best guess for each, and stop
  there: he answers in his next message. Then make it, look at it with preview_animation, fix
  what's off, and tell him in a line what you made.
- Keep replies short and plain. When you changed the board, say in a sentence what you did.
- Don't paste the outline back; refer to cards by what they say."""


def find_claude() -> str | None:
    """The bare ``claude`` binary (the shell's ``claude`` is a function that skips permissions)."""
    override = os.environ.get("CXBOARDS_CLAUDE")
    if override:
        return override
    found = shutil.which("claude")
    if found:
        return found
    for candidate in ("~/.local/bin/claude", "/opt/homebrew/bin/claude", "/usr/local/bin/claude"):
        path = Path(candidate).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def subscription_environment() -> dict[str, str]:
    """Drop API-key and provider overrides so the logged-in subscription is what's used."""
    env = dict(os.environ)
    for key in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY"):
        env.pop(key, None)
    return env


def workdir() -> Path:
    """Outside the home folder, so no CLAUDE.md above it is loaded (see the module docstring)."""
    path = Path(tempfile.gettempdir()) / "cxboards-chat"
    path.mkdir(parents=True, exist_ok=True)
    return path


def mcp_config(home: Path, base_url: str) -> Path:
    """An MCP config naming only the cxboards server (this venv's entry point)."""
    command = str(Path(sys.executable).with_name("cxboards"))
    config = {"mcpServers": {"cxboards": {"command": command, "args": ["mcp"], "env": {}}}}
    port = base_url.rsplit(":", 1)[-1]
    if port != "4870":
        config["mcpServers"]["cxboards"]["env"]["CXBOARDS_PORT"] = port
    path = home / "chat-mcp.json"
    path.write_text(json.dumps(config, indent=1))
    return path


def system_prompt(outline: str, selection: list[str]) -> str:
    parts = [BRIEF, f"Today is {date.today().isoformat()}.", "## The board Chris has open\n" + outline]
    if selection:
        parts.append("## Cards Chris has selected (his question is about these)\n" + "\n".join(selection))
    return "\n\n".join(parts)


def user_prompt(message: str, history: list[dict[str, Any]]) -> str:
    turns = [t for t in history if t.get("text")][-HISTORY_TURNS:]
    if not turns:
        return message
    lines = ["Our conversation so far:"]
    for turn in turns:
        who = "Chris" if turn["role"] == "user" else "You"
        lines.append(f"{who}: {turn['text']}")
    lines.append("")
    lines.append(f"Chris now asks: {message}")
    return "\n".join(lines)


def build_cmd(claude: str, prompt: str, system: str, model: str, mcp_path: Path) -> list[str]:
    return [
        claude, "-p", prompt,
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--model", model,
        "--mcp-config", str(mcp_path), "--strict-mcp-config",
        "--setting-sources", "project",
        "--permission-mode", "dontAsk",
        "--allowedTools", *ALLOWED_TOOLS,
        "--disallowedTools", *DISALLOWED_TOOLS,
        "--append-system-prompt", system,
    ]


def _event(kind: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": kind, **data}


def _tool_label(name: str) -> str:
    short = name.split("__")[-1]
    return TOOL_LABELS.get(short, short.replace("_", " "))


async def _drain(stream: asyncio.StreamReader | None, sink: list[str]) -> None:
    if stream is None:
        return
    async for raw in stream:
        sink.append(raw.decode("utf-8", errors="replace"))
        del sink[:-80]


async def run_turn(cmd: list[str], *, first_timeout: float = FIRST_ACTIVITY_TIMEOUT,
                   turn_timeout: float = TURN_TIMEOUT) -> AsyncIterator[dict[str, Any]]:
    """Run one turn and yield events: token {text}, tool {id, name, label, state}, done {text, cost}, error {message}.

    Stdout is read line by line with a large buffer (tool results can be long); stderr is
    drained alongside so the pipe never fills. The process is killed if the caller stops
    listening (Stop, or the panel closing)."""
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(workdir()),
        env=subscription_environment(),
        limit=16 * 1024 * 1024,
    )
    stderr: list[str] = []
    drain = asyncio.create_task(_drain(proc.stderr, stderr))
    text: list[str] = []
    tools: dict[int, str] = {}
    loop = asyncio.get_running_loop()
    deadline = loop.time() + turn_timeout
    seen_activity = False
    finished = False
    try:
        while True:
            budget = (first_timeout if not seen_activity else deadline - loop.time())
            if budget <= 0:
                yield _event("error", {"message": "That took too long, so it was stopped."})
                return
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=budget)  # type: ignore[union-attr]
            except asyncio.TimeoutError:
                yield _event("error", {"message": "Claude didn't answer in time, so it was stopped."})
                return
            if not raw:
                break
            seen_activity = True
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            kind = msg.get("type")
            if kind == "stream_event":
                event = msg.get("event") or {}
                etype = event.get("type")
                if etype == "content_block_delta" and (event.get("delta") or {}).get("type") == "text_delta":
                    piece = event["delta"].get("text", "")
                    text.append(piece)
                    yield _event("token", {"text": piece})
                elif etype == "content_block_start" and (event.get("content_block") or {}).get("type") == "tool_use":
                    name = event["content_block"].get("name", "tool")
                    if name in QUIET_TOOLS:
                        continue
                    tools[event.get("index", -1)] = name
                    yield _event("tool", {"index": event.get("index"), "name": name, "label": _tool_label(name), "state": "start"})
                elif etype == "content_block_stop" and event.get("index") in tools:
                    name = tools.pop(event["index"])
                    yield _event("tool", {"index": event["index"], "name": name, "label": _tool_label(name), "state": "stop"})
                elif etype == "message_start" and text and not text[-1].endswith("\n"):
                    # A new assistant message after tool use: keep its words apart from the last ones.
                    text.append("\n\n")
                    yield _event("token", {"text": "\n\n"})
            elif kind == "result":
                finished = True
                if msg.get("is_error") or msg.get("subtype") not in (None, "success"):
                    detail = msg.get("result") or msg.get("subtype") or "the turn failed"
                    yield _event("error", {"message": str(detail)[:500]})
                    return
                answer = "".join(text).strip() or str(msg.get("result") or "").strip()
                yield _event("done", {"text": answer, "cost": msg.get("total_cost_usd"),
                                      "turns": msg.get("num_turns")})
                return
        await proc.wait()
        if not finished:
            tail = "".join(stderr).strip().splitlines()[-6:]
            yield _event("error", {"message": "Claude stopped without answering." + (
                "\n" + "\n".join(tail) if tail else "")})
    finally:
        if proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass
        drain.cancel()
