"""The CXBoards HTTP API, its live event stream, and the built UI.

Local only: the server binds 127.0.0.1, refuses any Host header that isn't
this machine (DNS-rebinding guard), and requires an ``X-CXBoards`` header on
every write, which a cross-site form or fetch can't send without a CORS
preflight this server never grants.

The caller says who it is with ``X-CXBoards-Actor`` (``chris`` from the UI,
``agent`` from the MCP); that is how the UI knows which cards to highlight,
and whose undo stack a change lands on.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import mimetypes
import re
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import chat as chatlib
from . import formats, outline, themes
from .config import AUDIO_EXTENSIONS, MAX_FILE_BYTES, MAX_IMAGE_BYTES, VIDEO_EXTENSIONS, Config, load_config
from .events import Broadcaster
from .export import Exporter
from .locate import locate as default_locate
from .store import PATH_KINDS, Invalid, NotFound, Store
from .unfurl import unfurl as default_unfurl

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
HEX = re.compile(r"^\s*#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})\s*$")
ARTIFACTS_ADDRESS = "Muzik/Boards"


def kind_for(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in AUDIO_EXTENSIONS:
        return "audio"
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    return "file"


def create_app(
    config: Config | None = None,
    unfurl: Callable[[str], dict[str, Any]] = default_unfurl,
    export_delay: float = 1.5,
    locate: Callable[[str, int, float], list[Path]] = default_locate,
    opener: Callable[[list[str]], None] | None = None,
    rotator: Callable[[Path, Path, int], None] | None = None,
    claude: Callable[[], str | None] = chatlib.find_claude,
) -> FastAPI:
    config = config or load_config()
    store = Store(config)
    broadcaster = Broadcaster()
    exporter = Exporter(store, delay=export_delay)
    run_open = opener or (lambda args: subprocess.run(args, check=False, timeout=10))

    def sips_rotate(source: Path, target: Path, degrees: int) -> None:
        subprocess.run(["sips", "-r", str(degrees), str(source), "--out", str(target)],
                       check=True, capture_output=True, timeout=30)

    rotate_image = rotator or sips_rotate

    def on_change(board_id: str, rev: int, card_ids: list[str], actor: str, history_id: int | None) -> None:
        if rev < 0:  # the board was deleted: open windows move off it; its snapshot goes
            broadcaster.publish({"board_id": board_id, "deleted": True, "card_ids": [], "actor": actor})
            exporter.sweep()
            return
        event: dict[str, Any] = {"board_id": board_id, "rev": rev, "card_ids": card_ids, "actor": actor}
        if history_id is not None:
            event["history_id"] = history_id
            event["summary"] = store.history_summary(history_id)
        broadcaster.publish(event)
        exporter.schedule(board_id)

    store.listeners.append(on_change)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        broadcaster.bind(asyncio.get_running_loop())
        yield
        exporter.flush()

    app = FastAPI(title="CXBoards", lifespan=lifespan)
    app.state.store = store
    app.state.exporter = exporter
    app.state.broadcaster = broadcaster
    app.state.config = config

    allowed_hosts = {f"127.0.0.1:{config.port}", f"localhost:{config.port}", "127.0.0.1", "localhost", "testserver"}

    @app.middleware("http")
    async def guard(request: Request, call_next):
        if request.headers.get("host", "") not in allowed_hosts:
            return PlainTextResponse("Refused: host not allowed.", status_code=403)
        if request.method not in ("GET", "HEAD", "OPTIONS") and request.headers.get("x-cxboards") != "1":
            return JSONResponse({"error": "writes need the X-CXBoards header"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(NotFound)
    async def not_found(request: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=404)

    @app.exception_handler(Invalid)
    async def invalid(request: Request, exc: Invalid) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    def actor_of(request: Request) -> str:
        actor = request.headers.get("x-cxboards-actor", "chris")
        return actor if actor in ("chris", "agent") else "chris"

    def board_id_of(ref: str) -> str:
        return store.resolve_board(ref)["id"]

    def resolve_column(board_id: str, ref: str | None) -> str | None:
        if not ref:
            return None
        cards = store.cards(board_id)
        for card in cards:
            if card["kind"] == "column" and card["id"] == ref:
                return card["id"]
        matches = [c for c in cards if c["kind"] == "column" and c["text"].strip().lower() == ref.strip().lower()]
        if len(matches) == 1:
            return matches[0]["id"]
        if not matches:
            raise NotFound(f"no column {ref!r} on this board")
        raise Invalid(f"several columns are called {ref!r}; use its id")

    def prepare_spec(board_id: str, spec: dict[str, Any]) -> dict[str, Any]:
        """Turn an API card spec into store.add_card fields (imports images, resolves columns)."""
        spec = dict(spec)
        kind = spec.get("kind")
        data = dict(spec.pop("data", None) or {})
        for key in ("url", "items", "path", "hex"):
            if key in spec:
                data[key] = spec.pop(key)
        if kind == "image" and not data.get("file"):
            if data.get("path"):
                data["file"] = store.import_image_path(data.pop("path"))
            elif data.get("url") or spec.get("image_url"):
                data["file"] = import_image_url(data.pop("url", None) or spec.pop("image_url"))
            else:
                raise Invalid("an image card needs a path or url")
        if kind == "media":  # "whatever this file is": audio, video, or a file card
            kind = kind_for(data.get("path", ""))
        if kind == "note" and HEX.match(spec.get("text") or ""):  # a hex code alone becomes a swatch
            kind, data, spec["text"] = "swatch", {**data, "hex": spec["text"].strip()}, ""
        out = {
            "kind": kind,
            "text": spec.get("text") or spec.get("title") or "",
            "data": data,
            "color": spec.get("color"),
        }
        column = resolve_column(board_id, spec.get("column") or spec.get("column_id"))
        if column:
            out["column_id"] = column
            if spec.get("index") is not None:
                out["index"] = int(spec["index"])
        for key in ("near", "side", "x", "y", "w"):
            if spec.get(key) not in (None, ""):
                out[key] = spec[key]
        if spec.get("unsorted") or spec.get("tray"):
            out["tray"] = True
        if spec.get("avoid"):
            out["avoid"] = True
        return out

    def import_image_url(url: str) -> str:
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                resp = client.get(url)
        except httpx.HTTPError as exc:
            raise Invalid(f"couldn't fetch {url}: {exc}") from exc
        if resp.status_code >= 400:
            raise Invalid(f"couldn't fetch {url}: HTTP {resp.status_code}")
        if len(resp.content) > MAX_IMAGE_BYTES:
            raise Invalid("image is larger than 25 MB")
        name = Path(resp.url.path).name or "image.png"
        if "." not in name:
            name += "." + (resp.headers.get("content-type", "image/png").split("/")[-1].split(";")[0] or "png")
        return store.save_image_bytes(resp.content, name)

    def after_add(cards: list[dict[str, Any]]) -> None:
        for card in cards:
            if card["kind"] == "link" and not card["data"].get("title"):
                threading.Thread(target=fill_preview, args=(card["id"], card["data"]["url"]), daemon=True).start()

    def fill_preview(card_id: str, url: str) -> None:
        preview = unfurl(url)
        try:
            store.update_card(card_id, data=preview, actor="system")
        except (NotFound, Invalid):
            pass

    # ------------------------------------------------------------------ boards

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "boards": len(store.list_boards()), "home": str(config.home)}

    @app.get("/api/boards")
    def list_boards() -> list[dict[str, Any]]:
        return store.list_boards()

    @app.post("/api/boards")
    def create_board(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        parent = body.get("parent") or body.get("parent_id")
        parent_id = board_id_of(parent) if parent else None
        template = body.get("template")
        template_id = board_id_of(template) if template else None
        return store.create_board(
            body.get("title", ""), body.get("description", ""), parent_id, actor_of(request), template_id=template_id
        )

    @app.get("/api/boards/{ref}")
    def get_board(ref: str) -> dict[str, Any]:
        return store.board_state(board_id_of(ref))

    @app.get("/api/boards/{ref}/outline", response_class=PlainTextResponse)
    def get_outline(ref: str) -> str:
        return outline.board_outline(store, board_id_of(ref), config.base_url)

    @app.patch("/api/boards/{board_id}")
    def update_board(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return store.update_board(
            board_id_of(board_id), body.get("title"), body.get("description"), actor_of(request),
            is_template=body.get("is_template"), theme=body["theme"] if "theme" in body else ...,
        )

    @app.get("/api/themes")
    def theme_catalog() -> list[dict[str, Any]]:
        return themes.catalog()

    @app.post("/api/themes/preview")
    def theme_preview(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return {"palette": themes.palette(themes.normalize(body.get("theme")))}
        except themes.ThemeError as exc:
            raise Invalid(str(exc)) from exc

    @app.delete("/api/boards/{board_id}")
    def delete_board(board_id: str, request: Request) -> dict[str, Any]:
        trash_id = store.delete_board(board_id, actor_of(request))
        exporter.sweep()
        return {"ok": True, "trash_id": trash_id}

    @app.post("/api/boards/{board_id}/duplicate")
    def duplicate_board(board_id: str, request: Request, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        parent = body.get("parent")
        return store.duplicate_board(
            board_id_of(board_id),
            parent_id=board_id_of(parent) if parent else None,
            title=body.get("title"),
            actor=actor_of(request),
            as_template=bool(body.get("template")),
        )

    @app.post("/api/boards/{board_id}/export")
    def export_now(board_id: str) -> dict[str, Any]:
        board = store.resolve_board(board_id)
        path = exporter.export_board(board["id"])
        return {"path": str(path), "artifacts": f"{ARTIFACTS_ADDRESS}/{board['export_slug']}"}

    # ------------------------------------------------------------------ documents and print

    def download(content: bytes, filename: str, media_type: str) -> Response:
        quoted = filename.replace('"', "")
        return Response(content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{quoted}"'})

    @app.get("/api/boards/{board_id}/export.{fmt}")
    def export_document(board_id: str, fmt: str) -> Response:
        board = store.resolve_board(board_id)
        stem = board["export_slug"]
        if fmt == "md":
            return download(formats.bundle(store, board["id"])[0].encode(), f"{stem}.md", "text/markdown; charset=utf-8")
        if fmt == "txt":
            return download(formats.to_text(formats.bundle(store, board["id"])[0]).encode(), f"{stem}.txt", "text/plain; charset=utf-8")
        if fmt == "zip":
            return download(formats.to_zip(store, board["id"]), f"{stem}.zip", "application/zip")
        if fmt == "docx":
            try:
                content = formats.to_docx(store, board["id"])
            except (RuntimeError, subprocess.SubprocessError) as exc:
                raise Invalid(f"couldn't make the Word file: {exc}") from exc
            return download(content, f"{stem}.docx",
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        raise NotFound(f"no export called {fmt}: use md, txt, docx or zip")

    @app.post("/api/boards/{board_id}/export/vault")
    def export_vault(board_id: str) -> dict[str, Any]:
        path = formats.to_vault(store, store.resolve_board(board_id)["id"], config.vault)
        return {"path": str(path), "relative": str(path.relative_to(config.vault))}

    @app.get("/print/{board_id}/", response_class=HTMLResponse)
    def print_view(board_id: str) -> HTMLResponse:
        """The board's snapshot, opened for printing (Save as PDF from the print dialog)."""
        board = store.resolve_board(board_id)
        page = exporter.export_board(board["id"]).read_text(encoding="utf-8")
        script = "<script>addEventListener('load',()=>setTimeout(()=>print(),400))</script>"
        page = page.replace("<head>", f'<head><base href="/print/{board["id"]}/">', 1).replace("</body>", script + "</body>")
        page = page.replace("@media screen and (prefers-color-scheme: dark)", "@media not all")  # print on paper colours
        return HTMLResponse(page)

    @app.get("/print/{board_id}/media/{name}")
    def print_media(board_id: str, name: str) -> FileResponse:
        board = store.resolve_board(board_id)
        path = exporter.root / board["export_slug"] / "media" / name
        if "/" in name or not path.is_file():
            raise NotFound(name)
        return FileResponse(path)

    @app.get("/api/proxy")
    def proxy(url: str) -> Response:
        """A remote image (a link's thumbnail), fetched once and kept: works offline, exports to PNG."""
        if not re.match(r"^https?://", url):
            raise Invalid("only http(s) images")
        cache = config.uploads_dir / ".proxy"
        cache.mkdir(exist_ok=True)
        key = hashlib.sha256(url.encode()).hexdigest()[:24]
        hit = next(cache.glob(f"{key}.*"), None)
        if hit is None:
            try:
                with httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": "CXBoards/0.1"}) as client:
                    resp = client.get(url)
            except httpx.HTTPError as exc:
                raise NotFound(f"couldn't fetch the image: {exc}") from exc
            kind = resp.headers.get("content-type", "").split(";")[0]
            if resp.status_code >= 400 or not kind.startswith("image/") or len(resp.content) > MAX_IMAGE_BYTES:
                raise NotFound("not an image")
            hit = cache / f"{key}.{kind.split('/')[1].replace('jpeg', 'jpg').replace('svg+xml', 'svg')}"
            hit.write_bytes(resp.content)
        return FileResponse(hit, headers={"Cache-Control": "max-age=604800"})

    # ------------------------------------------------------------------ undo / redo

    @app.post("/api/boards/{board_id}/undo")
    def undo(board_id: str) -> dict[str, Any]:
        return store.undo(board_id=board_id_of(board_id))

    @app.post("/api/boards/{board_id}/redo")
    def redo(board_id: str) -> dict[str, Any]:
        return store.redo(board_id_of(board_id))

    @app.post("/api/history/{history_id}/undo")
    def undo_step(history_id: int) -> dict[str, Any]:
        return store.undo(history_id=history_id)

    @app.get("/api/boards/{board_id}/history")
    def history(board_id: str) -> list[dict[str, Any]]:
        return store.history(board_id_of(board_id))

    # ------------------------------------------------------------------ trash

    @app.get("/api/trash")
    def trash(board: str | None = None) -> list[dict[str, Any]]:
        return store.list_trash(board_id_of(board) if board else None)

    @app.post("/api/trash/{trash_id}/restore")
    def restore(trash_id: str, request: Request) -> dict[str, Any]:
        return store.restore(trash_id, actor_of(request))

    @app.delete("/api/trash/{trash_id}")
    def purge(trash_id: str, request: Request) -> dict[str, Any]:
        store.purge(trash_id, actor_of(request))
        return {"ok": True}

    @app.delete("/api/trash")
    def empty_trash(request: Request) -> dict[str, Any]:
        return {"emptied": store.empty_trash(actor_of(request))}

    # ------------------------------------------------------------------ search

    @app.get("/api/search")
    def search(q: str = "") -> list[dict[str, Any]]:
        return store.search(q)

    # ------------------------------------------------------------------ cards

    @app.post("/api/boards/{board_id}/cards")
    def add_card(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        board_id = board_id_of(board_id)
        spec = prepare_spec(board_id, body)
        card = store.add_card(board_id, spec.pop("kind"), actor=actor_of(request), **spec)
        after_add([card])
        return card

    @app.post("/api/boards/{board_id}/cards/batch")
    def add_cards(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> list[dict[str, Any]]:
        """Many cards in one revision. A column spec may carry its own ``cards``.

        Placement chains: when the first card is placed ``near`` something, each
        later card in the batch is placed beside the one before it.
        """
        board_id = board_id_of(board_id)
        specs = body.get("cards") or []
        if not isinstance(specs, list) or not specs:
            raise Invalid("send a non-empty list of cards")
        actor = actor_of(request)
        created: list[dict[str, Any]] = []
        with store.batch():  # one revision, one event, one undo step for the whole batch
            previous: str | None = None
            for raw in specs:
                raw = dict(raw)
                children = raw.pop("cards", None) or []
                if previous and raw.get("near") is None and body.get("chain", True) and specs[0].get("near"):
                    raw["near"] = previous
                spec = prepare_spec(board_id, raw)
                card = store.add_card(board_id, spec.pop("kind"), actor=actor, **spec)
                created.append(card)
                previous = card["id"]
                if card["kind"] == "column":
                    for child in children:
                        child_spec = prepare_spec(board_id, {**child, "column": card["id"]})
                        created.append(store.add_card(board_id, child_spec.pop("kind"), actor=actor, **child_spec))
        after_add(created)
        return [store.card(c["id"]) for c in created]

    @app.patch("/api/cards/{card_id}")
    def update_card(card_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        data = dict(body.get("data") or {})
        for key in ("url", "items", "path", "hex"):
            if key in body:
                data[key] = body[key]
        if "url" in data:  # a new link: drop the old preview so nothing stale survives
            data.update(title=None, description=None, image=None, site=None, embed=None)
        kind = body.get("kind")
        text = body.get("text")
        if text is not None and HEX.match(text) and store.card(card_id)["kind"] == "note":
            kind, data, text = "swatch", {**data, "hex": text.strip()}, ""
        card = store.update_card(
            card_id,
            text=text,
            data=data or None,
            color=body.get("color"),
            w=body.get("w"),
            h=body.get("h"),
            locked=body.get("locked"),
            z=body.get("z"),
            kind=kind,
            actor="system" if set(body) <= {"h"} else actor_of(request),
        )
        if "url" in data:
            after_add([card])
        return card

    @app.post("/api/cards/{card_id}/move")
    def move_card(card_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        card = store.card(card_id)
        target_board = board_id_of(body["board"]) if body.get("board") else None
        column = body.get("column", body.get("column_id"))
        column_id = "" if column == "" else resolve_column(card["board_id"], column) if column else None
        unsorted = body.get("unsorted", body.get("tray"))
        return store.move_card(
            card_id,
            x=body.get("x"),
            y=body.get("y"),
            column_id=column_id,
            index=body.get("index"),
            near=body.get("near") or None,
            side=body.get("side") or "right",
            board_id=target_board,
            tray=bool(unsorted) if unsorted is not None else None,
            actor=actor_of(request),
        )

    @app.get("/api/cards/{card_id}/board")
    def card_board(card_id: str) -> dict[str, Any]:
        return {"board_id": store.card(card_id)["board_id"]}

    @app.delete("/api/cards/{card_id}")
    def delete_card(card_id: str, request: Request) -> dict[str, Any]:
        return {"ok": True, "trash_id": store.delete_card(card_id, actor_of(request))}

    @app.post("/api/cards/delete")
    def delete_cards(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return {"ok": True, "trash_ids": store.delete_cards(body.get("card_ids") or [], actor_of(request))}

    @app.post("/api/cards/duplicate")
    def duplicate_cards(request: Request, body: dict[str, Any] = Body(...)) -> list[dict[str, Any]]:
        board = body.get("board")
        return store.duplicate_cards(
            body.get("card_ids") or [],
            board_id=board_id_of(board) if board else None,
            x=body.get("x"),
            y=body.get("y"),
            actor=actor_of(request),
        )

    @app.post("/api/cards/move-to-board")
    def move_to_board(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        moved = store.move_cards(
            body.get("card_ids") or [], board_id_of(body.get("board", "")),
            x=body.get("x"), y=body.get("y"), actor=actor_of(request),
        )
        return {"moved": moved}

    @app.post("/api/boards/{board_id}/positions")
    def set_positions(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return {"moved": store.set_positions(board_id_of(board_id), body.get("positions") or {}, actor_of(request))}

    @app.post("/api/boards/{board_id}/arrange")
    def arrange(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        order = store.arrange(board_id_of(board_id), body.get("card_ids") or None, body.get("mode", "grid"), actor_of(request))
        return {"arranged": order}

    @app.post("/api/boards/{board_id}/group")
    def group(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return store.group_into_column(board_id_of(board_id), body.get("card_ids") or [], body.get("title", ""), actor_of(request))

    @app.post("/api/boards/{board_id}/sub-board")
    def sub_board(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return store.make_sub_board(board_id_of(board_id), body.get("card_ids") or [], body.get("title", ""), actor_of(request))

    # ------------------------------------------------------------------ lines and labels

    @app.post("/api/connectors")
    def add_connector(request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """A line between two cards; the board is theirs."""
        return store.add_connector(
            body.get("from") or body.get("from_id", ""), body.get("to") or body.get("to_id", ""),
            label=body.get("label", ""), color=body.get("color"), style=body.get("style", "solid"),
            arrow=body.get("arrow", "end"), curve=body.get("curve", True), actor=actor_of(request),
        )

    @app.patch("/api/connectors/{connector_id}")
    def update_connector(connector_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return store.update_connector(connector_id, actor=actor_of(request), **body)

    @app.delete("/api/connectors/{connector_id}")
    def delete_connector(connector_id: str, request: Request) -> dict[str, Any]:
        store.delete_connector(connector_id, actor_of(request))
        return {"ok": True}

    @app.get("/api/labels")
    def labels() -> list[dict[str, Any]]:
        return store.labels()

    @app.post("/api/cards/labels")
    def label_cards(request: Request, body: dict[str, Any] = Body(...)) -> list[dict[str, Any]]:
        return store.label_cards(body.get("card_ids") or [], body.get("names") or [], bool(body.get("remove")), actor_of(request))

    @app.patch("/api/labels/{label_id}")
    def update_label(label_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return store.update_label(label_id, body.get("name"), body.get("color"), actor_of(request))

    @app.delete("/api/labels/{label_id}")
    def delete_label(label_id: str, request: Request) -> dict[str, Any]:
        store.delete_label(label_id, actor_of(request))
        return {"ok": True}

    @app.post("/api/uploads")
    def upload(file: UploadFile = File(...)) -> dict[str, Any]:
        """An image kept without making a card (a link's replacement thumbnail)."""
        name = store.save_image_bytes(file.file.read(), file.filename or "image.png")
        return {"file": name, "url": f"/media/{name}"}

    # ------------------------------------------------------------------ media and files

    def placement(board_id: str, x: float | None, y: float | None, column: str | None, unsorted: bool) -> dict[str, Any]:
        fields: dict[str, Any] = {}
        column_id = resolve_column(board_id, column)
        if unsorted:
            fields["tray"] = True
        elif column_id:
            fields["column_id"] = column_id
        elif x is not None and y is not None:
            fields.update(x=x, y=y)
        return fields

    @app.post("/api/boards/{board_id}/images")
    def upload_image(
        board_id: str,
        request: Request,
        file: UploadFile = File(...),
        x: float | None = Form(None),
        y: float | None = Form(None),
        column: str | None = Form(None),
        unsorted: bool = Form(False),
    ) -> dict[str, Any]:
        board_id = board_id_of(board_id)
        name = store.save_image_bytes(file.file.read(), file.filename or "image.png")
        return store.add_card(board_id, "image", actor=actor_of(request), data={"file": name},
                              **placement(board_id, x, y, column, unsorted))

    @app.post("/api/boards/{board_id}/locate")
    def locate_dropped(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """A file dropped from Finder: find it on disk by name + size + mtime and point a card at it."""
        board_id = board_id_of(board_id)
        found = locate(str(body.get("name", "")), int(body.get("size", -1)), float(body.get("mtime", 0)))
        if not found:
            raise NotFound(f"couldn't find {body.get('name')} on disk")
        path = found[0]
        card = store.add_card(
            board_id, kind_for(path), actor=actor_of(request), data={"path": str(path)},
            **placement(board_id, body.get("x"), body.get("y"), body.get("column"), bool(body.get("unsorted"))),
        )
        return {**card, "matches": [str(p) for p in found]}

    @app.post("/api/boards/{board_id}/files")
    def upload_file(
        board_id: str,
        request: Request,
        file: UploadFile = File(...),
        x: float | None = Form(None),
        y: float | None = Form(None),
        column: str | None = Form(None),
        unsorted: bool = Form(False),
    ) -> dict[str, Any]:
        """The fallback when a dropped file can't be found on disk: keep a copy, and say so on the card."""
        board_id = board_id_of(board_id)
        content = file.file.read(MAX_FILE_BYTES + 1)
        if len(content) > MAX_FILE_BYTES:
            raise Invalid("file is larger than 2 GB")
        name = file.filename or "file"
        path = store.save_file_bytes(content, name)
        return store.add_card(
            board_id, kind_for(name), actor=actor_of(request), data={"path": str(path), "name": name, "copied": True},
            **placement(board_id, x, y, column, unsorted),
        )

    @app.post("/api/cards/{card_id}/rotate")
    def rotate(card_id: str, request: Request, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        """Turn an image card 90° (or -90, 180). A rotated copy is made; the original stays in uploads, so undo works."""
        card = store.card(card_id)
        if card["kind"] != "image":
            raise Invalid("only images rotate")
        degrees = int(body.get("degrees", 90)) % 360
        if degrees not in (90, 180, 270):
            raise Invalid("rotate by 90, 180 or -90 degrees")
        source = store.upload_path(card["data"]["file"])
        target = config.uploads_dir / f".rotating-{card_id}{source.suffix}"
        try:
            rotate_image(source, target, degrees)
            name = store.save_image_bytes(target.read_bytes(), source.name)
        except (OSError, subprocess.SubprocessError) as exc:
            raise Invalid(f"couldn't rotate the image: {exc}") from exc
        finally:
            target.unlink(missing_ok=True)
        return store.update_card(card_id, data={"file": name, "crop": None}, actor=actor_of(request))

    @app.post("/api/cards/{card_id}/thumbnail")
    def thumbnail(card_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """A link card's picture, from an image file on disk (the native app's Finder drop)."""
        if store.card(card_id)["kind"] != "link":
            raise Invalid("only link cards have a thumbnail")
        name = store.import_image_path(str(body.get("path", "")))
        return store.update_card(card_id, data={"image": f"/media/{name}", "hide_image": False}, actor=actor_of(request))

    @app.get("/media/{name}")
    def media(name: str) -> FileResponse:
        return FileResponse(store.upload_path(name))

    def card_file(card_id: str) -> Path:
        card = store.card(card_id)
        if card["kind"] not in PATH_KINDS:
            raise NotFound("this card has no file")
        path = Path(card["data"]["path"])
        if not path.is_file():
            raise NotFound(f"{path} isn't reachable (is the drive mounted?)")
        return path

    @app.get("/api/cards/{card_id}/file")
    def file(card_id: str) -> FileResponse:
        path = card_file(card_id)
        media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        return FileResponse(path, media_type=media_type, headers={"Content-Disposition": "inline"})

    @app.get("/api/cards/{card_id}/audio")
    def audio(card_id: str) -> FileResponse:
        return file(card_id)

    @app.post("/api/cards/{card_id}/open")
    def open_file(card_id: str, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        """Open the card's file in its app (a .flp opens FL Studio), or reveal it in Finder."""
        path = card_file(card_id)
        run_open(["open", "-R", str(path)] if body.get("reveal") else ["open", str(path)])
        return {"ok": True, "path": str(path)}

    # ------------------------------------------------------------------ Ask (chat about a board)

    @app.get("/api/chat/info")
    def chat_info() -> dict[str, Any]:
        return {"available": bool(claude()), "models": chatlib.MODELS, "default": chatlib.DEFAULT_MODEL}

    @app.get("/api/boards/{board_id}/chats")
    def list_chats(board_id: str) -> list[dict[str, Any]]:
        return store.chats(board_id_of(board_id))

    @app.get("/api/chats/{chat_id}")
    def get_chat(chat_id: str) -> dict[str, Any]:
        return store.chat(chat_id)

    @app.delete("/api/chats/{chat_id}")
    def delete_chat(chat_id: str) -> dict[str, Any]:
        store.delete_chat(chat_id)
        return {"ok": True}

    @app.post("/api/boards/{board_id}/chat")
    def ask(board_id: str, body: dict[str, Any] = Body(...)) -> StreamingResponse:
        """One turn of the chat, streamed: chat, token, tool, done | error (server-sent events)."""
        board = store.resolve_board(board_id)
        message = str(body.get("message") or "").strip()
        if not message:
            raise Invalid("ask something")
        model = body.get("model") if body.get("model") in chatlib.MODELS else chatlib.DEFAULT_MODEL
        chat_id = body.get("chat_id") or store.start_chat(board["id"], message)
        history = store.chat(chat_id)["messages"]
        state = store.board_state(board["id"])
        by_id = {c["id"]: c for c in state["cards"]}
        picked = [by_id[i] for i in body.get("selection") or [] if i in by_id]
        store.add_message(chat_id, {"role": "user", "text": message, "selection": [c["id"] for c in picked]})
        binary = claude()

        async def stream():
            yield f"event: chat\ndata: {json.dumps({'chat_id': chat_id})}\n\n"
            if not binary:
                note = "Claude Code isn't installed (no `claude` on this Mac), so Ask can't answer."
                store.add_message(chat_id, {"role": "assistant", "text": "", "error": note})
                yield f"event: error\ndata: {json.dumps({'message': note})}\n\n"
                return
            system = chatlib.system_prompt(
                outline.board_outline(store, board["id"], config.base_url),
                [outline.card_line(c) for c in picked],
            )
            cmd = chatlib.build_cmd(
                binary, chatlib.user_prompt(message, history), system, model,
                chatlib.mcp_config(config.home, config.base_url),
            )
            text: list[str] = []
            tools: list[str] = []
            outcome: dict[str, Any] = {"stopped": True}
            try:
                async with contextlib.aclosing(chatlib.run_turn(cmd)) as events:
                    async for event in events:
                        kind = event.pop("event")
                        if kind == "token":
                            text.append(event["text"])
                        elif kind == "tool" and event.get("state") == "start":
                            tools.append(event["label"])
                        elif kind == "done":
                            outcome = {"cost": event.get("cost")}
                            text = [event.get("text") or "".join(text)]
                        elif kind == "error":
                            outcome = {"error": event["message"]}
                        yield f"event: {kind}\ndata: {json.dumps(event)}\n\n"
            finally:
                store.add_message(chat_id, {
                    "role": "assistant", "text": "".join(text).strip(), "tools": tools, "model": model, **outcome,
                })

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------ live events

    @app.get("/api/events")
    async def events(request: Request) -> StreamingResponse:
        queue = broadcaster.subscribe()

        async def stream():
            try:
                yield "retry: 2000\n\n"
                while True:
                    if await request.is_disconnected():
                        break
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"event: change\ndata: {json.dumps(event)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": ping\n\n"
            finally:
                broadcaster.unsubscribe(queue)

        return StreamingResponse(
            stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        )

    # ------------------------------------------------------------------ UI

    if (WEB_DIST / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    def index() -> HTMLResponse:
        page = WEB_DIST / "index.html"
        if not page.is_file():
            return HTMLResponse("<p>CXBoards UI isn't built yet: run <code>npm run build</code> in web/.</p>")
        return HTMLResponse(page.read_text(encoding="utf-8"), headers={"Cache-Control": "no-cache"})

    @app.get("/", response_class=HTMLResponse)
    def root() -> HTMLResponse:
        return index()

    @app.get("/b/{board_id}", response_class=HTMLResponse)
    def board_page(board_id: str) -> HTMLResponse:
        return index()

    @app.get("/clip", response_class=HTMLResponse)
    def clip_page() -> HTMLResponse:
        return index()

    for name in ("icon.png", "favicon.png", "favicon.ico", "apple-touch-icon.png"):
        def serve(name: str = name) -> Response:
            path = WEB_DIST / name
            return FileResponse(path) if path.is_file() else Response(status_code=404)
        app.add_api_route(f"/{name}", serve, methods=["GET"], include_in_schema=False)

    return app
