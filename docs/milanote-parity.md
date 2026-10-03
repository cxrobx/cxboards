# Milanote parity: what CXBoards covers, will cover, and skips

Source: every article in Milanote's help center "Adding & organizing content" collection
(30), plus Sharing & collaboration, Exporting, Presentation mode, Web clippers and Keyboard
shortcuts. Read 2026-10-02. The bar is **parity for one person running it locally**, with
agents as the second "user". Collaboration, accounts and cloud features are out by design.

Legend: ✅ have · ⏭ skip (reason). Everything marked 🔨 in the first draft was built on 2026-10-02 in three
phases (commits aa2b1e6, 4cc5ad8, 435d5a7) and verified in the browser.

## Cards

| Milanote | CXBoards | Notes |
|---|---|---|
| Notes, double-click to create | ✅ | Markdown, not WYSIWYG |
| Text formatting shortcuts (⌘B/I/U, ⌘K link, ⌘J highlight, ⌘⇧X strike, ⌘⇧1/2 headings, lists, quote, code) | ✅ | Shortcuts insert markdown; `==highlight==` rendered |
| Note background colours / transparent | ✅ | Have an accent stripe; add tints |
| ⌘↵ while editing = next note below | ✅ | |
| To-do lists | ✅ | |
| To-do: indent (Tab / ⇧Tab) | ✅ | |
| To-do: due dates, assignees, reminders | ⏭ | CXTasks owns dated work; don't build a second task system |
| Links with previews | ✅ | |
| Link: toggle image / description, replace thumbnail | ✅ | |
| Link embeds that play inline (YouTube, Vimeo, Spotify, SoundCloud, Bandcamp, Apple Music, Mixcloud, Google Maps) | ✅ | Click to load the player, so the iframe doesn't steal drags. Some label-licensed YouTube music videos refuse to play embedded from a localhost page (YouTube's rule); the card still links out |
| Board shortcut (paste a board URL) | ✅ | |
| Images: paste, drop, upload, caption | ✅ | |
| Images: resize | ✅ | Width |
| Images: full-size view, download, crop, rotate | ✅ | Crop is stored on the card (non-destructive); rotate makes a rotated copy with `sips`, the original stays, undo works |
| Images: draw on image | ✅ | Shares the sketch engine |
| Image library search (Pexels), AI background removal | ⏭ | Third-party API; not session planning |
| Audio files, play/scrub | ✅ | Pointed at, never copied |
| Audio: loop, autoplay | ✅ | Loop only; autoplay on a board is noise |
| **Drag audio from Finder** | ✅ | Name + size + mtime → Spotlight → exact path. Fallback: bounded search of MuZik, then copy with a visible "copied" badge |
| Video files and embeds | ✅ | Same as audio: by path, streamed |
| Files (PDF, docs, design files…) | ✅ | By path; PDF previews inline; **Open** (default app, e.g. a `.flp` opens FL) and **Reveal in Finder** |
| Columns: add, reorder, out, title, count, group selection | ✅ | |
| Columns: collapse, width | ✅ | |
| Nested boards + breadcrumbs | ✅ | |
| Lines / arrows between cards: label, colour, weight, arrowheads, curve | ✅ | Card-to-card. Free-floating lines that point at empty canvas ⏭ |
| Colour swatches (hex/RGB/HSL, hex typed in a note becomes a swatch, eyedropper) | ✅ | Eyedropper from images ⏭ (browser support is Chromium-only) |
| Sketch card + drawing on the board | ✅ | Pen, sizes 1–4, six inks, eraser, stroke undo; SVG paths. Drawing happens on a sketch card (⇧D) rather than loose on the canvas |
| Documents (full-screen long-form, export MD/PDF/Word) | ✅ | Full-screen focus editor on a note; export via the board exports |
| Tables with formulas | ⏭ | Markdown tables in notes already render; formulas aren't session planning |
| Map cards | ✅ | Comes free with the Google Maps embed |
| Synced notes | ⏭ | Niche; a board shortcut covers "show this in two places" |
| Comments, @mentions, reactions | ⏭ | Multi-user. (An agent can leave its reasoning in a note.) |

## Organising

| Milanote | CXBoards | Notes |
|---|---|---|
| Undo / redo | ✅ | Per transaction, agent edits included; refuses if the cards changed since |
| Trash with restore | ✅ | Soft delete, 90 days, restore to where it was |
| Delete key | ✅ | Safe once trash + undo exist |
| Duplicate (⌘D, ⌥-drag), copy / cut / paste across boards | ✅ | |
| Duplicate a whole board | ✅ | |
| Move content between boards (drop on a board card, "Move to…") | ✅ | API and MCP have it; UI doesn't |
| Lock position | ✅ | |
| Send back / forward | ✅ | |
| Unsorted tray per board | ✅ | Where clips and agent drops land without cluttering the canvas |
| Labels (colours, rename everywhere, find by label) | ✅ | Agents can label too |
| Search across every board (⌘F), recent boards | ✅ | |
| Templates (board → template, new board from template) | ✅ | E.g. a "Session plan" template |
| Home board | ✅ | The sidebar tree does this job |

## Navigation, view, keyboard

| Milanote | CXBoards | Notes |
|---|---|---|
| Pan (space-drag, scroll), zoom (pinch) | ✅ | |
| Zoom keys, fit | ✅ | `Z` / ⌘+ / ⌘− / ⌘0 |
| Arrow-key nudge (⇧ = more), ⌘A, Esc | ✅ | |
| ⌘[ / ⌘] back/forward, ⌘U parent board | ✅ | |
| Dark mode | ✅ | Follows the system |
| Interface size | ⏭ | Browser zoom does it |
| Presentation mode (hide tools, click a card to focus) | ✅ | |

## Sharing, export, capture

| Milanote | CXBoards | Notes |
|---|---|---|
| Export Markdown, plain text | ✅ | Optionally straight into the vault |
| Export PNG, PDF | ✅ | PDF = the print view (`/print/<board>/`, Save as PDF); PNG = the whole board rendered client-side, link thumbnails via the local image proxy |
| Export Word | ✅ | Via pandoc from the Markdown, if pandoc is installed |
| ZIP of images and files | ✅ | |
| Static copy for reading elsewhere | ✅ | Onyx snapshots (beyond Milanote) |
| Web clipper (images, text, links → a board) | ✅ | A bookmarklet opening a local clip page, into Unsorted. No extension to maintain |
| Share links, read-only, passwords, real-time collaboration, notifications | ⏭ | Single user, local only |
| iPhone / iPad / Android apps, iOS share sheet | ⏭ | Local desktop tool; the server binds 127.0.0.1 |

## Beyond Milanote (already here)

Agents as first-class editors (MCP, live arrival with highlight, per-step Undo), an Ask chat
panel that can change the board, layout tools instead of coordinates, audio streamed in place from the ChrisX drive, Onyx snapshots with
highlight-to-ask, vault-MCP indexing.

## Known limits (2026-10-02)

- Annotations drawn on an image cover the whole image; on a cropped image they're shown over the crop
  frame, so a crop after drawing can misalign them.
- A card can't sit in two columns; synced notes are skipped (see above).
- Headless Chromium hangs on the print view's automatic `print()`; real browsers show the print dialog.
