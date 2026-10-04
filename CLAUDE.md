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

- **The app**: `/Applications/CXBoards.app` (`com.cx.cxboards`, source `app/CXBoards.swift`,
  built by `app/build-app.sh`, no Xcode project) is a borderless native window around the
  same server, like Onyx: it starts the LaunchAgent if it's down (kickstart, else
  bootstrap), hands Finder drops to the page as **real paths** (`window.cxboardsNativeDrop`),
  shows alert/confirm/prompt as sheets, saves downloads to ~/Downloads, opens outside links
  in the browser, and answers `cxboards://b/<board id>`. The window drags by the page's top
  28 px band, the board header and the sidebar's empty space (`web/src/native.ts` posts the
  mouse-down to the app's `cxDrag` handler); controls, the board list and the canvas keep
  their clicks. Verify with `scripts/selftest-app.sh` (the real app against the live server
  on a throwaway board, cleaned up after).

- **Ask** (the chat panel, ⌘/ or the Ask button): each turn is one headless `claude -p` on
  the subscription (`src/cxboards/chat.py`): the bare binary, `--strict-mcp-config` with only
  the cxboards MCP, Read/Grep/Glob + web allowed, shell and edits refused
  (`--permission-mode dontAsk`), `--setting-sources project` (Chris's hooks don't fire),
  cwd outside home (no 41k-token ~/CLAUDE.md reload), a short brief + the board outline +
  any selected cards in `--append-system-prompt`, earlier turns as a transcript. Chats live
  in the `chats` table (not board content: no undo, no trash). Default model Sonnet; a turn
  costs about $0.04 of quota. Tests use a fake `claude` (tests/test_chat.py); a real turn
  was checked by hand on 2026-10-03.

- **Themes** (Board ▸ Theme…): a board has a preset (vault, chrisx, film, studio, paper,
  midnight, sage, rose) or custom ground/ink/accent + font + corners, and the whole app wears
  the open board's theme. `src/cxboards/themes.py` is the only place palettes are computed
  (board state, picker previews, Onyx snapshots all read it); muted text and accents are
  derived and kept readable, and unreadable custom colours are corrected. Vault = no theme =
  the app's own look, following macOS light/dark. `web/src/theme.ts` writes the palette onto
  the page and tells CXBoards.app (`cxTheme`), whose window appearance and background follow
  and are remembered for the next launch. Chris X takes chrisx.art's DESIGN.md literally:
  #000 cards on #000, cream ink and accent, Fraunces + Poppins 300, square everything.

- **Sidebar** (`web/src/Sidebar.tsx`): a folder is a board for keeping boards in, so its boards
  are cards on its canvas and agents file into it with `move_board`. `boards.is_folder` only gives
  an empty one the folder icon; any board with boards inside shows as a folder. Right-click makes
  them (empty space: New folder / New board; a board: New folder inside, New board inside,
  Rename, Duplicate, Move into, Delete), names are typed in place, and a folder's chevron closes
  it (remembered; opening a board opens the folders above it). The dock is Onyx's: pinned, or
  unpinned (⌘\ or the pin) so it floats out from a 24 px strip on the left edge (40 ms in; away
  400 ms after the pointer leaves, unless its menu, a name field, a resize or a drag is in
  progress); its right edge drags the width, 200 px to half the window, double-click resets. Pin,
  width and closed folders are per-browser localStorage (`cxboards.sidebar`, `cxboards.side-w`,
  `cxboards.shut`), written straight onto the elements so hovering doesn't re-render the board.

- **Templates** (`templates/`, `src/cxboards/templates.py`): a library of boards as YAML files,
  `templates/<use case>/<slug>.yaml`, use cases ordered in `templates/categories.yaml` (Milanote's
  gallery, de-duplicated and rewritten in our words, plus our own Music). `templates/README.md`
  documents the format and carries a generated index (`scripts/template-index.py`). The loader
  refuses a slug, name or source used twice; the app loads leniently (a broken file is left out
  and listed under `problems`), the tests strictly. `layout.flow` places a template in rows and
  `Store.build_board` writes it as one undo step. Used from New board (a browser by use case, with
  search and previews), `POST /api/boards {template: slug}`, and the MCP's `list_templates` +
  `create_board(template=slug)`. Check new files with `scripts/check-template.py`. Boards Chris
  makes into templates are still DB boards (`is_template`), shown under *Yours*.

- **Animations** (`motion/`, `src/cxboards/motion.py`, `web/src/Motion.tsx`): a picture that moves,
  every frame drawn with JavaScript (Kevin Ngo's style; Milanote's "Head in the Clouds" cover): an
  `animation` card, or an `image` card with `data.motion = {code, loop}` drawing over its picture.
  `motion/runtime.js` is the one drawing runtime (a hand-drawn `pen`, noise, easing, `cover()`),
  run in two places: the board's `<iframe sandbox="allow-scripts">` at `/motion/runner` (served
  with a CSP that allows no loads or connections; a worker on an OffscreenCanvas, a 2-second
  watchdog), and `motion/render.mjs` in Node with `@napi-rs/canvas` (`motion/node_modules`, run
  `npm install` there) for the check before every save (broken or endless code is refused),
  previews for agents, the poster frame snapshots show, and mp4/gif export. Node is found even
  under nvm (`motion.find_node`). The board plays only what's on screen, not zoomed far out, six
  at once, and under Reduce Motion only on hover. Made from Ask or agents: `motion_guide` (the
  questions to ask first, the style, the API), `add_cards` kind animation, `animate`,
  `animation_code`, `preview_animation` (an image: it must stay `structured_output=False`). By
  hand: right-click ▸ Animate… (Ask) / Animation code / Export.

Data lives in `~/Library/Application Support/CXBoards/` (`cxboards.db`, `uploads/`,
`export/`). `CXBOARDS_HOME` / `CXBOARDS_PORT` override both (the tests do).

## Invariants (machine-checked in `tests/`)

1. Agents never send coordinates; placement (`layout.py`) never overlaps a card. "About
   here" adds (toolbar) take the nearest free spot; a pointer drop or paste keeps its spot.
2. Deleting never destroys: cards and boards go to the `trash` table (90 days, restorable);
   a column's cards return to the canvas; a board card's board becomes top-level.
3. One transaction = one rev bump = one event = one snapshot = one undo step.
4. Undo restores exactly the rows one step touched, or refuses if any changed since (an
   agent's later edit is never clobbered). Undo is per actor: ⌘Z is Chris's stack; an
   agent's step is undone by its id (the toast's Undo). System writes fold into the step
   they follow. The journal is fed by triggers generated from the live column list.
5. CXBoards writes only inside its home, except exports Chris asks for (downloads, and
   the vault note, which never overwrites a note he has edited since). Audio, video and
   files on disk are **only read**: cards point at them, Finder drops are resolved to the
   real path (name + size + mtime → Spotlight), and snapshots stream audio from
   `:4870/api/cards/<id>/file`. Onyx refuses symlinks outside its folders (tried: 404).
6. Local-only guard: Host must be 127.0.0.1/localhost, and every write needs the
   `X-CXBoards: 1` header (cross-site forms/fetches can't send it without a preflight).
7. Snapshots never carry `<script>`: note HTML is escaped, drawing strokes are stored
   only as path commands + numbers with hex colours, and an animation shows its poster frame.
   Animation code runs only in the sandbox (no same-origin, no network) or server-side in Node.

## Run / verify

```bash
.venv/bin/python -m pytest -q          # 357 tests: invariants, API, export, MCP, chat, themes, folders, templates (each built), animations, phases 1-3
app/build-app.sh                       # build + install CXBoards.app (Apple Development signed)
scripts/selftest-app.sh                # the app's own end-to-end check (drops, dialogs, sidebar, downloads, links)
scripts/install.sh                     # build UI, (re)install LaunchAgent, wait for health
launchctl kickstart -k gui/$(id -u)/com.cx.cxboards.server   # restart after Python edits
cd web && npm run dev                  # UI on :4871, proxying the API on :4870
tail -f ~/Library/Logs/cxboards.log
```

A Python change needs a restart; a UI change needs `npm run build` (the server serves
`web/dist`). Before a schema change on the live data, back up the database
(`sqlite3 cxboards.db ".backup cxboards.db.bak-<date>"`); old databases migrate in place
(`ADDED_COLUMNS` in `store.py`).

Playwright gotchas: a one-step `dragTo` doesn't trigger React Flow drags (drive
`page.mouse` in steps); `window.prompt` is intercepted by Playwright MCP; the print
view's automatic `print()` wedges headless Chromium (fetch its HTML instead).

Milanote parity, what's built and what's skipped (with reasons): `docs/milanote-parity.md`.

## Icon

`assets/icon/candidate-2.png` (amber waveform) is the one in use, copied to
`web/public/`. Codex generated all three on 2026-10-02 against the CX app family
(`house-reference.png`).
