"""A board as a document: Markdown, plain text, Word (via pandoc), a ZIP, or a
note in the Obsidian vault.

Reading order is the board's: top to bottom, left to right; a column becomes a
heading with its cards under it. Images travel as files beside the Markdown
(or into the vault's attachments folder); sketches are written out as SVG.
Audio, video and other files stay where they are and are listed by path.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .store import Store

ImageRef = Callable[[str], str]  # uploads file name -> how the document refers to it


def _sketch_svg(data: dict[str, Any]) -> str:
    w, h = (data.get("box") or [400, 300])[:2]
    paths = "".join(f'<path d="{p["d"]}" fill="{p.get("color") or "#222"}"/>' for p in data.get("paths") or [])
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{paths}</svg>'


def _title(card: dict[str, Any]) -> str:
    data = card["data"]
    text = re.sub(r"[#*_`>=~]+", "", (card["text"] or "").split("\n")[0]).strip()
    return (text or data.get("title") or data.get("name") or data.get("hex") or card["kind"])[:60]


class BoardDocument:
    """Builds the Markdown for one board and collects the media files it refers to."""

    def __init__(self, store: Store, board_id: str, image_ref: ImageRef, sketch_ref: ImageRef):
        self.store = store
        self.board_id = board_id
        self.image_ref = image_ref
        self.sketch_ref = sketch_ref
        self.images: list[str] = []
        self.sketches: dict[str, str] = {}  # file name -> svg
        self.files: list[str] = []

    def card(self, card: dict[str, Any]) -> str:
        data, kind, text = card["data"], card["kind"], card["text"] or ""
        if kind == "note":
            return text.strip()
        if kind == "todo":
            head = f"**{text}**\n" if text else ""
            items = "\n".join(
                f"{'  ' * int(i.get('indent') or 0)}- [{'x' if i['done'] else ' '}] {i['text']}" for i in data.get("items", [])
            )
            return head + items
        if kind == "link":
            parts = [f"[{data.get('title') or data['url']}]({data['url']})"]
            if data.get("description") and not data.get("hide_desc"):
                parts.append(f"> {data['description']}")
            if text:
                parts.append(text)
            return "\n".join(parts)
        if kind == "image":
            self.images.append(data["file"])
            return self._embed(self.image_ref(data["file"]), text)
        if kind in ("audio", "video", "file"):
            self.files.append(data.get("path", ""))
            glyph = {"audio": "♪", "video": "▶", "file": "▤"}[kind]
            return f"{glyph} **{data.get('name')}** — `{data.get('path')}`" + (f"\n{text}" if text else "")
        if kind == "swatch":
            return f"■ `{data.get('hex')}`" + (f" {text}" if text else "")
        if kind == "animation":
            poster = (data.get("motion") or {}).get("poster")
            if poster:
                self.images.append(poster)
                return self._embed(self.image_ref(poster), (text or "animation") + " (moves in CXBoards)")
            return f"▶ animation: {text or 'untitled'} (moves in CXBoards)"
        if kind == "sketch":
            name = f"{card['id']}.svg"
            self.sketches[name] = _sketch_svg(data)
            return self._embed(self.sketch_ref(name), text or "sketch")
        if kind == "board":
            child = card.get("board") or {}
            return f"→ board: **{child.get('title', '?')}** ({child.get('card_count', 0)} cards)"
        return text

    @staticmethod
    def _embed(ref: str, caption: str) -> str:
        """An image embed: Obsidian's ![[file]] (caption on the next line) or markdown's ![caption](path)."""
        if ref.startswith("[["):
            return f"!{ref}" + (f"\n{caption}" if caption else "")
        return f"![{caption}]({ref})"

    def markdown(self, frontmatter: dict[str, Any] | None = None) -> str:
        state = self.store.board_state(self.board_id)
        board = state["board"]
        out: list[str] = []
        if frontmatter:
            out.append("---")
            out.extend(f"{k}: {json.dumps(v) if isinstance(v, str) and ':' in v else v}" for k, v in frontmatter.items())
            out.append("---\n")
        out.append(f"# {board['title']}\n")
        if board["description"]:
            out.append(board["description"] + "\n")
        by_id = {c["id"]: c for c in state["cards"]}
        for card in self.store.reading_order(self.board_id):
            if card["kind"] == "column":
                out.append(f"## {card['text'] or 'Untitled column'}\n")
                for child in card.get("children", []):
                    out.append(self.card(child) + "\n")
            else:
                out.append(self.card(card) + "\n")
        tray = [c for c in state["cards"] if c["tray"]]
        if tray:
            out.append("## Unsorted\n")
            out.extend(self.card(c) + "\n" for c in tray)
        if state["connectors"]:
            out.append("## Lines\n")
            for line in state["connectors"]:
                a, b = by_id.get(line["from_id"]), by_id.get(line["to_id"])
                if a and b:
                    label = f": {line['label']}" if line["label"] else ""
                    out.append(f"- {_title(a)} → {_title(b)}{label}")
            out.append("")
        return "\n".join(out).rstrip() + "\n"


def to_text(markdown: str) -> str:
    text = re.sub(r"^---\n.*?\n---\n", "", markdown, flags=re.S)
    text = re.sub(r"!\[\[([^\]]+)\]\]|!\[([^\]]*)\]\([^)]*\)", lambda m: f"[image: {m.group(1) or m.group(2) or 'image'}]", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", text)
    text = re.sub(r"(\*\*|__|==|~~|`)", "", text)
    return re.sub(r"^#+\s*", "", text, flags=re.M)


def bundle(store: Store, board_id: str) -> tuple[str, BoardDocument]:
    doc = BoardDocument(store, board_id, image_ref=lambda f: f"media/{f}", sketch_ref=lambda f: f"media/{f}")
    return doc.markdown(), doc


def to_zip(store: Store, board_id: str) -> bytes:
    markdown, doc = bundle(store, board_id)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("board.md", markdown)
        for name in dict.fromkeys(doc.images):
            zf.write(store.upload_path(name), f"media/{name}")
        for name, svg in doc.sketches.items():
            zf.writestr(f"media/{name}", svg)
        if doc.files:
            zf.writestr("files on disk.txt", "\n".join(dict.fromkeys(doc.files)) + "\n")
    return buf.getvalue()


def to_docx(store: Store, board_id: str) -> bytes:
    if not shutil.which("pandoc"):
        raise RuntimeError("Word export needs pandoc (brew install pandoc)")
    markdown, doc = bundle(store, board_id)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "media").mkdir()
        for name in dict.fromkeys(doc.images):
            shutil.copy2(store.upload_path(name), root / "media" / name)
        for name, svg in doc.sketches.items():
            (root / "media" / name).write_text(svg)
        (root / "board.md").write_text(markdown)
        subprocess.run(
            ["pandoc", "board.md", "-f", "markdown", "-o", "board.docx", "--resource-path", "."],
            cwd=root, check=True, capture_output=True, timeout=60,
        )
        return (root / "board.docx").read_bytes()


def to_vault(store: Store, board_id: str, vault: Path) -> Path:
    """Write the board as a note in the vault's Inbox, images into its attachments folder.

    A note this export wrote before is replaced only if nobody has edited it since;
    otherwise a numbered copy is written next to it."""
    board = store.board(board_id)
    notes = vault / "Inbox" / "Quick Notes"
    attachments = vault / "Other" / "Attachments"
    notes.mkdir(parents=True, exist_ok=True)
    attachments.mkdir(parents=True, exist_ok=True)
    doc = BoardDocument(store, board_id, image_ref=lambda f: f"[[{f}]]", sketch_ref=lambda f: f"[[{f}]]")
    markdown = doc.markdown(frontmatter={
        "cxboards_id": board_id,
        "exported": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "live": f"{store.config.base_url}/b/{board_id}",
    })
    for name in dict.fromkeys(doc.images):
        target = attachments / name
        if not target.exists():
            shutil.copy2(store.upload_path(name), target)
    for name, svg in doc.sketches.items():
        (attachments / name).write_text(svg)

    ledger_path = store.config.home / "vault-exports.json"
    try:
        ledger = json.loads(ledger_path.read_text())
    except (OSError, ValueError):
        ledger = {}
    safe = re.sub(r'[\\/:*?"<>|]+', "-", board["title"]).strip() or "Board"
    target = notes / f"{safe} (CXBoards).md"
    n = 2
    while target.exists():
        written = ledger.get(str(target))
        current = hashlib.sha256(target.read_bytes()).hexdigest()
        if written == current:
            break  # ours, untouched since: safe to replace
        target = notes / f"{safe} (CXBoards) {n}.md"
        n += 1
    target.write_text(markdown)
    ledger[str(target)] = hashlib.sha256(markdown.encode()).hexdigest()
    ledger_path.write_text(json.dumps(ledger, indent=1))
    return target
