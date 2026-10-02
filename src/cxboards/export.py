"""Static snapshots of each board, for Onyx.

Every board is written to ``<home>/export/<slug>/index.html`` (plus a
``media/`` folder) a moment after it changes. That export folder is linked once
into Onyx's Artifacts (``Muzik/Boards``), so each board shows up there as a
page, gets highlight-to-ask, and is indexed by the vault MCP.

The page needs no JavaScript. Cards are absolutely positioned in reading order;
when the reader is narrower than the board, a container query drops them into
one readable column, which is why the DOM order is the reading order.
"""

from __future__ import annotations

import html
import json
import os
import re
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import markdown as md

from .store import NotFound, Store

MARKER = ".cxboards-board"
TARGET_WIDTH = 1100.0
PAD = 32.0


def render_markdown(text: str) -> str:
    # Raw HTML is never passed through: a snapshot is a page Onyx runs.
    out = md.markdown(
        (text or "").replace("<", "&lt;"),
        extensions=["fenced_code", "tables", "sane_lists", "nl2br"],
    )
    return re.sub(r"==([^=\n]+)==", r"<mark>\1</mark>", out)


def _clip(cx: float, cy: float, tx: float, ty: float, rect: tuple[float, float, float, float]) -> tuple[float, float]:
    """Where the line from a rect's centre (cx, cy) towards (tx, ty) leaves the rect."""
    x, y, w, h = rect
    dx, dy = tx - cx, ty - cy
    if dx == 0 and dy == 0:
        return cx, cy
    scale = min(
        (w / 2) / abs(dx) if dx else float("inf"),
        (h / 2) / abs(dy) if dy else float("inf"),
    )
    return cx + dx * scale, cy + dy * scale


def _e(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


class Exporter:
    def __init__(self, store: Store, delay: float = 1.5):
        self.store = store
        self.delay = delay
        self._timers: dict[str, threading.Timer] = {}
        self._lock = threading.Lock()

    @property
    def root(self) -> Path:
        return self.store.config.export_dir

    # ------------------------------------------------------------------ scheduling

    def schedule(self, board_id: str) -> None:
        with self._lock:
            old = self._timers.pop(board_id, None)
            if old:
                old.cancel()
            timer = threading.Timer(self.delay, self._fire, args=(board_id,))
            timer.daemon = True
            self._timers[board_id] = timer
            timer.start()

    def _fire(self, board_id: str) -> None:
        with self._lock:
            self._timers.pop(board_id, None)
        try:
            self.export_board(board_id)
        except NotFound:
            pass

    def flush(self) -> None:
        with self._lock:
            pending = list(self._timers)
            for timer in self._timers.values():
                timer.cancel()
            self._timers.clear()
        for board_id in pending:
            try:
                self.export_board(board_id)
            except NotFound:
                pass

    # ------------------------------------------------------------------ writing

    def export_all(self) -> list[Path]:
        written = [self.export_board(b["id"]) for b in self.store.list_boards()]
        self.sweep()
        return written

    def sweep(self) -> None:
        """Remove snapshot folders whose board is gone. Only folders carrying our marker."""
        live = {b["id"]: b["export_slug"] for b in self.store.list_boards()}
        for folder in self.root.iterdir() if self.root.exists() else []:
            marker = folder / MARKER
            if not marker.is_file():
                continue
            board_id = marker.read_text().strip()
            if live.get(board_id) != folder.name:
                shutil.rmtree(folder)

    def export_board(self, board_id: str) -> Path:
        state = self.store.board_state(board_id)
        board = state["board"]
        folder = self.root / board["export_slug"]
        media = folder / "media"
        folder.mkdir(parents=True, exist_ok=True)
        page = self.render(state, media)
        tmp = folder / "index.html.tmp"
        tmp.write_text(page, encoding="utf-8")
        os.replace(tmp, folder / "index.html")
        (folder / MARKER).write_text(board_id)
        self._prune_media(state["cards"], media)
        self.sweep()
        return folder / "index.html"

    def _prune_media(self, cards: list[dict[str, Any]], media: Path) -> None:
        if not media.exists():
            return
        keep = {c["data"]["file"] for c in cards if c["kind"] == "image"}
        for entry in media.iterdir():
            if entry.name not in keep:
                entry.unlink()

    def _place_image(self, card: dict[str, Any], media: Path) -> str:
        name = card["data"]["file"]
        self.store.copy_upload(name, media)
        return f"media/{name}"

    def _audio_src(self, card: dict[str, Any]) -> str:
        # Audio is streamed by the running CXBoards server, never copied or
        # linked: bounces stay where they live, and Onyx won't serve a symlink
        # that resolves outside its own folders (tried 2026-10-02: 404).
        return f"{self.store.config.base_url}/api/cards/{card['id']}/audio"

    # ------------------------------------------------------------------ rendering

    def _slug_of(self, board_id: str) -> str | None:
        try:
            return self.store.board(board_id)["export_slug"]
        except NotFound:
            return None

    def render_card(self, card: dict[str, Any], media: Path, position: str = "") -> str:
        kind, data = card["kind"], card["data"]
        if kind == "note":
            body = f'<div class="md">{render_markdown(card["text"])}</div>'
        elif kind == "todo":
            items = "".join(
                f'<li class="{"done" if i["done"] else ""}"><span class="box">{"☑" if i["done"] else "☐"}</span>{_e(i["text"])}</li>'
                for i in data.get("items", [])
            )
            title = f'<div class="card-title">{_e(card["text"])}</div>' if card["text"] else ""
            body = f"{title}<ul class=\"todo\">{items}</ul>"
        elif kind == "link":
            show_image = data.get("image") and not data.get("hide_image")
            image = f'<img class="thumb" src="{_e(data["image"])}" alt="" loading="lazy">' if show_image else ""
            if data.get("embed"):
                image += f'<div class="plays">▶ plays in CXBoards · {_e(data["embed"].get("provider"))}</div>'
            show_desc = data.get("description") and not data.get("hide_desc")
            desc = f'<div class="desc">{_e(data.get("description"))}</div>' if show_desc else ""
            note = f'<div class="md">{render_markdown(card["text"])}</div>' if card["text"] else ""
            body = (
                f'{image}<a class="link-title" href="{_e(data["url"])}">{_e(data.get("title") or data["url"])}</a>'
                f'{desc}<div class="site">{_e(data.get("site"))}</div>{note}'
            )
        elif kind == "image":
            src = self._place_image(card, media)
            caption = f'<div class="caption">{_e(card["text"])}</div>' if card["text"] else ""
            turn = f' style="transform:rotate({int(data["rotate"])}deg)"' if data.get("rotate") else ""
            crop = data.get("crop")
            img = f'<img class="picture" src="{_e(src)}" alt="{_e(card["text"])}"{turn}>'
            if crop:
                # Show only the cropped region: scale the image up inside a frame of the crop's shape.
                sw, sh = 100 / crop["w"], 100 / crop["h"]
                img = (
                    f'<div class="crop" style="aspect-ratio:{crop.get("aspect") or crop["w"] / crop["h"]:.4f}">'
                    f'<img src="{_e(src)}" alt="{_e(card["text"])}" style="width:{sw * 100:.2f}%;height:{sh * 100:.2f}%;'
                    f'left:{-crop["x"] * sw:.2f}%;top:{-crop["y"] * sh:.2f}%"></div>'
                )
            sketch = self._sketch_svg(data.get("annotations")) if data.get("annotations") else ""
            body = f'<div class="pic">{img}{sketch}</div>{caption}'
        elif kind == "audio":
            src = self._audio_src(card)
            note = f'<div class="md">{render_markdown(card["text"])}</div>' if card["text"] else ""
            body = (
                f'<div class="card-title">♪ {_e(data.get("name"))}</div>'
                f'<audio controls preload="none" src="{_e(src)}"></audio>{note}'
                f'<div class="path">{_e(data.get("path"))}</div>'
            )
        elif kind in ("video", "file"):
            note = f'<div class="md">{render_markdown(card["text"])}</div>' if card["text"] else ""
            ext = (data.get("ext") or "").upper() or "FILE"
            player = (
                f'<video controls preload="metadata" src="{_e(self._audio_src(card))}"></video>' if kind == "video" else ""
            )
            body = (
                f'{player}<div class="card-title"><span class="ext">{_e(ext)}</span> {_e(data.get("name"))}</div>{note}'
                f'<div class="path">{_e(data.get("path"))}</div>'
            )
        elif kind == "swatch":
            note = f'<div class="caption">{_e(card["text"])}</div>' if card["text"] else ""
            body = f'<div class="chip-color" style="background:{_e(data.get("hex"))}"></div><div class="hex">{_e(data.get("hex"))}</div>{note}'
        elif kind == "sketch":
            caption = f'<div class="caption">{_e(card["text"])}</div>' if card["text"] else ""
            body = self._sketch_svg(data) + caption
        elif kind == "board":
            child = card.get("board") or {}
            slug = self._slug_of(child.get("id", ""))
            href = f"../{slug}/index.html" if slug else "#"
            body = (
                f'<a class="board-link" href="{_e(href)}"><span class="board-glyph">▦</span>'
                f'<span class="card-title">{_e(child.get("title"))}</span>'
                f'<span class="site">{child.get("card_count", 0)} cards</span></a>'
            )
        else:
            body = ""
        labels = card.get("labels") or []
        if labels:
            chips = "".join(
                f'<span class="label" style="--label:{_e(lb["color"])}">{_e(lb["name"])}</span>' for lb in labels
            )
            body += f'<div class="labels">{chips}</div>'
        style = ";".join(s for s in (position, f"--card-accent:{_e(card['color'])}" if card.get("color") else "") if s)
        style_attr = f' style="{style}"' if style else ""
        fill = " filled" if data.get("fill") and card.get("color") else ""
        return f'<article class="card card-{kind}{fill}" id="{card["id"]}"{style_attr}>{body}</article>'

    @staticmethod
    def _sketch_svg(data: dict[str, Any] | None) -> str:
        data = data or {}
        w, h = (data.get("box") or [400, 300])[:2]
        paths = "".join(
            f'<path d="{_e(p.get("d"))}" fill="{_e(p.get("color") or "currentColor")}"/>' for p in data.get("paths") or []
        )
        return f'<svg class="sketch" viewBox="0 0 {float(w):.0f} {float(h):.0f}" preserveAspectRatio="none">{paths}</svg>'

    def _lines_svg(self, state: dict[str, Any], left: float, top: float, width: float, height: float) -> str:
        cards = {c["id"]: c for c in state["cards"]}
        out = []
        for line in state.get("connectors") or []:
            ends = []
            for cid in (line["from_id"], line["to_id"]):
                card = cards.get(cid)
                if card and card["column_id"]:
                    card = cards.get(card["column_id"])
                if not card or card["tray"]:
                    break
                ends.append((card["x"] - left, card["y"] - top, card["w"], card["h"]))
            if len(ends) != 2:
                continue
            (ax, ay, aw, ah), (bx, by, bw, bh) = ends
            acx, acy, bcx, bcy = ax + aw / 2, ay + ah / 2, bx + bw / 2, by + bh / 2
            x1, y1 = _clip(acx, acy, bcx, bcy, ends[0])
            x2, y2 = _clip(bcx, bcy, acx, acy, ends[1])
            color = _e(line.get("color") or "currentColor")
            dash = ' stroke-dasharray="7 6"' if line.get("style") == "dashed" else ""
            start = ' marker-start="url(#arrow)"' if line.get("arrow") == "both" else ""
            end = ' marker-end="url(#arrow)"' if line.get("arrow") in ("end", "both") else ""
            if line.get("curve"):
                mx, my = (x1 + x2) / 2, (y1 + y2) / 2
                nx, ny = -(y2 - y1) * 0.18, (x2 - x1) * 0.18
                d = f"M{x1:.0f},{y1:.0f} Q{mx + nx:.0f},{my + ny:.0f} {x2:.0f},{y2:.0f}"
                lx, ly = mx + nx / 2, my + ny / 2
            else:
                d = f"M{x1:.0f},{y1:.0f} L{x2:.0f},{y2:.0f}"
                lx, ly = (x1 + x2) / 2, (y1 + y2) / 2
            out.append(f'<path d="{d}" stroke="{color}" style="color:{color}"{dash}{start}{end}/>')
            if line.get("label"):
                out.append(f'<text x="{lx:.0f}" y="{ly:.0f}" text-anchor="middle" dy="-6">{_e(line["label"])}</text>')
        if not out:
            return ""
        return (
            f'<svg class="lines" width="{width:.0f}" height="{height:.0f}">'
            '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
            'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker></defs>'
            + "".join(out) + "</svg>"
        )

    def render(self, state: dict[str, Any], media: Path) -> str:
        board = state["board"]
        order = self.store.reading_order(board["id"])
        canvas = [c for c in order]
        if canvas:
            left = min(c["x"] for c in canvas) - PAD
            top = min(c["y"] for c in canvas) - PAD
            width = max(c["x"] + c["w"] for c in canvas) - left + PAD
            height = max(c["y"] + c["h"] for c in canvas) - top + PAD
        else:
            left = top = 0.0
            width, height = TARGET_WIDTH, 200.0
        zoom = max(0.55, min(1.0, TARGET_WIDTH / width))
        parts = []
        for card in canvas:
            style = f"left:{card['x'] - left:.0f}px;top:{card['y'] - top:.0f}px;width:{card['w']:.0f}px"
            if card["kind"] == "column":
                inner = "".join(self.render_card(child, media) for child in card.get("children", []))
                title = _e(card["text"]) or "&nbsp;"
                parts.append(
                    f'<section class="column" id="{card["id"]}" style="{style}"><h3>{title}</h3>{inner}</section>'
                )
            else:
                parts.append(self.render_card(card, media, position=style))
        lines = self._lines_svg(state, left, top, width, height)
        if lines:
            parts.insert(0, lines)
        crumbs = state["breadcrumbs"][:-1]
        trail = " / ".join(
            f'<a href="../{_e(self._slug_of(b["id"]))}/index.html">{_e(b["title"])}</a>' for b in crumbs
        )
        when = datetime.now().strftime("%Y-%m-%d %H:%M")
        live = f"{self.store.config.base_url}/b/{board['id']}"
        description = f'<p class="subtitle">{_e(board["description"])}</p>' if board["description"] else ""
        return TEMPLATE.format(
            title=_e(board["title"]),
            trail=f'<p class="eyebrow">{trail} /</p>' if trail else '<p class="eyebrow">CXBoards</p>',
            description=description,
            meta=f'Snapshot {when} · rev {board["rev"]} · <a href="{_e(live)}">open the live board</a>',
            width=f"{width:.0f}",
            height=f"{height:.0f}",
            zoom=f"{zoom:.3f}",
            cards="\n".join(parts) or '<p class="empty">This board is empty.</p>',
            board_id=_e(board["id"]),
            data=_e(json.dumps({"board": board["id"], "rev": board["rev"]})),
        )


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="generator" content="CXBoards" data-board="{data}">
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&display=swap">
<style>
:root {{
  --ivory:#FDF6E3; --slate:#000; --gray-100:#EDE8D6; --gray-300:#E0D7B8; --gray-500:#666; --gray-700:#333;
  --white:#FDF6E3; --clay:#CB4B16; --amber:#B07A1E; --card:#FFFDF6;
  --mono:"JetBrains Mono","SF Mono",ui-monospace,Menlo,monospace;
  --shadow:0 1px 2px rgba(0,0,0,.05),0 8px 20px -14px rgba(0,0,0,.25);
  color-scheme:light;
}}
@media screen and (prefers-color-scheme: dark) {{
  :root {{
    --ivory:#1A1A1A; --slate:#C4C5B5; --gray-100:#232323; --gray-300:#333; --gray-500:#95968B; --gray-700:#AEAFA1;
    --white:#202020; --clay:#FAB387; --amber:#E0A33A; --card:#222;
    --shadow:0 1px 2px rgba(0,0,0,.4),0 8px 20px -14px rgba(0,0,0,.8);
    color-scheme:dark;
  }}
  h1 {{ color:#F078A0; }}
  .column h3 {{ color:#E6C37D; }}
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; padding:40px 24px 80px; background:var(--ivory); color:var(--slate); font-family:var(--mono); font-size:13px; line-height:1.55; }}
a {{ color:var(--clay); }}
header {{ max-width:1100px; margin:0 auto 28px; }}
.eyebrow {{ font-size:11px; text-transform:uppercase; letter-spacing:.08em; color:var(--gray-500); margin:0 0 10px; }}
.eyebrow a {{ color:inherit; }}
h1 {{ font-size:28px; line-height:1.2; margin:0 0 6px; }}
.subtitle {{ color:var(--gray-500); margin:0; max-width:70ch; font-size:14px; }}
.meta {{ color:var(--gray-500); font-size:11px; margin-top:10px; }}
.board-frame {{ container-type:inline-size; max-width:100%; overflow-x:auto; }}
.canvas {{ position:relative; width:{width}px; height:{height}px; zoom:{zoom}; margin:0 auto; }}
.card, .column {{ position:absolute; }}
.card {{ background:var(--card); border:1px solid var(--gray-300); border-left:3px solid var(--card-accent, var(--gray-300)); border-radius:8px; padding:12px 14px; box-shadow:var(--shadow); overflow-wrap:anywhere; }}
.column {{ background:var(--gray-100); border:1px solid var(--gray-300); border-radius:10px; padding:0 12px 12px; }}
.column h3 {{ font-size:13px; margin:0; padding:14px 2px 10px; color:var(--gray-700); }}
.column .card {{ position:static; margin-bottom:8px; }}
.card-title {{ font-weight:600; margin-bottom:6px; }}
.md p {{ margin:0 0 .5em; }} .md p:last-child {{ margin-bottom:0; }}
.md h1, .md h2, .md h3 {{ font-size:14px; margin:.2em 0 .4em; color:var(--slate); }}
.md ul, .md ol {{ margin:.2em 0 .5em; padding-left:1.3em; }}
.md code {{ background:var(--gray-100); padding:0 3px; border-radius:3px; }}
.todo {{ list-style:none; margin:0; padding:0; }}
.todo li {{ display:flex; gap:8px; padding:2px 0; }}
.todo li.done {{ color:var(--gray-500); text-decoration:line-through; }}
.box {{ color:var(--amber); }}
.thumb {{ width:calc(100% + 28px); margin:-12px -14px 10px; border-radius:8px 8px 0 0; display:block; aspect-ratio:16/9; object-fit:cover; object-position:center 30%; }}
.picture {{ width:calc(100% + 28px); margin:-12px -14px 0; border-radius:8px; display:block; }}
.caption {{ margin-top:10px; color:var(--gray-700); }}
.link-title {{ font-weight:600; display:block; text-decoration:none; }}
.desc {{ color:var(--gray-700); margin-top:4px; }}
.site, .path {{ color:var(--gray-500); font-size:11px; margin-top:6px; }}
audio {{ width:100%; margin:4px 0; }}
.board-link {{ display:flex; flex-direction:column; gap:4px; text-decoration:none; color:var(--slate); }}
.board-glyph {{ font-size:28px; color:var(--amber); line-height:1; }}
.empty {{ color:var(--gray-500); text-align:center; padding:40px; }}
mark {{ background:color-mix(in srgb, var(--amber) 35%, transparent); color:inherit; padding:0 2px; border-radius:2px; }}
.card.filled {{ background:color-mix(in srgb, var(--card-accent) 16%, var(--card)); }}
.labels {{ display:flex; flex-wrap:wrap; gap:4px; margin-top:8px; }}
.label {{ font-size:10px; padding:1px 7px; border-radius:10px; background:color-mix(in srgb, var(--label) 22%, transparent); border:1px solid color-mix(in srgb, var(--label) 50%, transparent); }}
.plays {{ font-size:11px; color:var(--amber); margin:-4px 0 6px; }}
.ext {{ font-size:10px; font-weight:600; padding:2px 5px; border-radius:4px; background:var(--amber); color:#1a1a1a; }}
.chip-color {{ height:90px; margin:-12px -14px 8px; border-radius:7px 7px 0 0; }}
.hex {{ font-weight:600; }}
.pic {{ position:relative; margin:-12px -14px 0; }}
.pic .picture {{ margin:0; }}
.crop {{ position:relative; overflow:hidden; border-radius:8px; }}
.crop img {{ position:absolute; max-width:none; }}
.pic .sketch {{ position:absolute; inset:0; width:100%; height:100%; }}
svg.sketch {{ display:block; width:100%; height:auto; color:var(--slate); }}
video {{ width:calc(100% + 28px); margin:-12px -14px 8px; border-radius:8px 8px 0 0; background:#000; }}
svg.lines {{ position:absolute; left:0; top:0; overflow:visible; pointer-events:none; color:var(--gray-500); }}
svg.lines path {{ fill:none; stroke-width:2; }}
svg.lines text {{ font:11px var(--mono); fill:var(--gray-700); paint-order:stroke; stroke:var(--ivory); stroke-width:4px; }}
@container (max-width: 760px) {{ svg.lines {{ display:none; }} }}
@container (max-width: 760px) {{
  .canvas {{ width:auto; height:auto; zoom:1; }}
  .card, .column {{ position:static; width:auto !important; margin-bottom:12px; }}
}}
</style>
</head>
<body>
<header>
{trail}
<h1>{title}</h1>
{description}
<p class="meta">{meta}</p>
</header>
<main class="board-frame"><div class="canvas" data-board="{board_id}">
{cards}
</div></main>
</body>
</html>
"""
