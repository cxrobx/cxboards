# CXBoards

A local visual planning board (Milanote-shaped) that a person and their agents share.

- Boards of cards: notes (markdown, formatting keys, full-screen writer), to-dos, links
  (preview, and YouTube/Spotify/SoundCloud/Bandcamp/Vimeo/Apple Music/Maps players), images
  (crop, rotate, draw on), audio/video/files on disk (streamed or opened, never copied; a
  Finder drop is resolved to the real path), colour swatches, sketches, columns, nested
  boards and shortcuts, lines between cards, labels, an Unsorted tray.
- Undo/redo, a trash, duplicate and copy/paste across boards, lock, search across every
  board, templates, presentation mode, and exports (Markdown, text, Word, ZIP, PNG, PDF, a
  vault note), plus a bookmarklet that clips pages into a board.
- A stdio MCP (`cxboards mcp`) gives agents the same moves through the same API, with
  layout tools instead of coordinates. Their edits appear live in the open board.
- Every board is also written as a static, script-free HTML snapshot for reading elsewhere.
- **Themes per board**: presets (including Chris X and Film) or your own colours; the whole
  app, the native window and the board's Onyx page take on the open board's theme.
- **Ask**: a chat panel on the board, answered by Claude (headless `claude -p` on your
  subscription) with the board's own tools, so it can lay out, group, label and edit cards
  while you watch. Selected cards go with the question.

Open it as **CXBoards.app** (`app/build-app.sh` builds and installs it), or at http://127.0.0.1:4870
in a browser. The app adds real file paths for Finder drops, native dialogs, downloads, and
`cxboards://b/<board id>` links.

```bash
uv venv .venv && uv pip install -e '.[test]'
cd web && npm install && cd ..
scripts/install.sh            # build UI, install the LaunchAgent; the board is at http://127.0.0.1:4870
claude mcp add -s local cxboards -- "$PWD/.venv/bin/cxboards" mcp
```

See `CLAUDE.md` for how it fits together and what the tests guarantee.
