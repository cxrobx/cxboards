# CXBoards

A local visual planning board (Milanote-shaped) that a person and their agents share.

- Boards of cards: notes (markdown), to-dos, links (auto preview), images, audio (a file on
  disk, streamed, never copied), columns, nested boards.
- A stdio MCP (`cxboards mcp`) gives agents the same moves through the same API, with
  layout tools instead of coordinates. Their edits appear live in the open board.
- Every board is also written as a static, script-free HTML snapshot for reading elsewhere.

```bash
uv venv .venv && uv pip install -e '.[test]'
cd web && npm install && cd ..
scripts/install.sh            # build UI, install the LaunchAgent; the board is at http://127.0.0.1:4870
claude mcp add -s local cxboards -- "$PWD/.venv/bin/cxboards" mcp
```

See `CLAUDE.md` for how it fits together and what the tests guarantee.
