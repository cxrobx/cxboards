# CXBoards

A local, Milanote-shaped planning board that Chris and his agents share. Personal tool, one
user, never deployed. Built 2026-10-02 to plan creative sessions next to the artist MCP.

## Shape

- **One process** (`cxboards serve`, LaunchAgent `com.cx.cxboards.server`) on
  **`127.0.0.1:4870`**: FastAPI + SQLite API, the live event stream (`/api/events`, SSE),
  and the built React Flow UI from `web/dist`.
- **The MCP** (`cxboards mcp`, stdio) is a thin client of the same HTTP API, tagged
  `X-CXBoards-Actor: agent`, so agent edits land live and glow in the open board.
  Registered **local scope only**, in `~/Projects/artist-mcp` and here. Don't promote it
  to user scope; the context-budget tripwire (T203) trips on new user-scope servers.
- **Onyx**: every board writes a static snapshot to
  `~/Library/Application Support/CXBoards/export/<slug>/index.html` a moment after it
  changes. That `export/` folder is linked into Onyx Artifacts as **`Muzik/Boards`**, so
  boards appear in Onyx, get highlight-to-ask, and are indexed by the vault MCP.

Data lives in `~/Library/Application Support/CXBoards/` (`cxboards.db`, `uploads/`,
`export/`). `CXBOARDS_HOME` / `CXBOARDS_PORT` override both (the tests do).

## Invariants (machine-checked in `tests/`)

1. Agents never send coordinates; placement (`layout.py`) never overlaps a card.
2. Deleting a card never deletes other content (column → its cards return to the canvas;
   board card → that board becomes top-level).
3. One transaction = one rev bump = one event = one snapshot.
4. CXBoards writes only inside its home. Audio cards **only read** the bounce they point at.
   Snapshots stream audio from `:4870/api/cards/<id>/audio`; never copy or symlink it.
   Onyx refuses a symlink that resolves outside its folders (tried: 404).
5. Local-only guard: Host must be 127.0.0.1/localhost, and every write needs the
   `X-CXBoards: 1` header (cross-site forms/fetches can't send it without a preflight).
6. Snapshots never carry `<script>`; raw HTML in notes is escaped.

## Run / verify

```bash
.venv/bin/python -m pytest -q          # 31 tests: store invariants, API, export, MCP
scripts/install.sh                     # build UI, (re)install LaunchAgent, wait for health
launchctl kickstart -k gui/$(id -u)/com.cx.cxboards.server   # restart after Python edits
cd web && npm run dev                  # UI on :4871, proxying the API on :4870
tail -f ~/Library/Logs/cxboards.log
```

A Python change needs a restart; a UI change needs `npm run build` (the server serves
`web/dist`). Playwright: a one-step `dragTo` doesn't trigger React Flow drags. Drive
`page.mouse` in steps.

## Icon

`assets/icon/candidate-2.png` (amber waveform) is the one in use, copied to
`web/public/`. Codex generated all three on 2026-10-02 against the CX app family
(`house-reference.png`).
