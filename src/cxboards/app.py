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
import json
import mimetypes
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import outline
from .config import AUDIO_EXTENSIONS, MAX_FILE_BYTES, MAX_IMAGE_BYTES, VIDEO_EXTENSIONS, Config, load_config
from .events import Broadcaster
from .export import Exporter
from .locate import locate as default_locate
from .store import PATH_KINDS, Invalid, NotFound, Store
from .unfurl import unfurl as default_unfurl

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
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
) -> FastAPI:
    config = config or load_config()
    store = Store(config)
    broadcaster = Broadcaster()
    exporter = Exporter(store, delay=export_delay)
    run_open = opener or (lambda args: subprocess.run(args, check=False, timeout=10))

    def on_change(board_id: str, rev: int, card_ids: list[str], actor: str, history_id: int | None) -> None:
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
            board_id, body.get("title"), body.get("description"), actor_of(request), is_template=body.get("is_template")
        )

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
        card = store.update_card(
            card_id,
            text=body.get("text"),
            data=data or None,
            color=body.get("color"),
            w=body.get("w"),
            h=body.get("h"),
            locked=body.get("locked"),
            z=body.get("z"),
            kind=body.get("kind"),
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

    for name in ("icon.png", "favicon.png", "favicon.ico", "apple-touch-icon.png"):
        def serve(name: str = name) -> Response:
            path = WEB_DIST / name
            return FileResponse(path) if path.is_file() else Response(status_code=404)
        app.add_api_route(f"/{name}", serve, methods=["GET"], include_in_schema=False)

    return app
