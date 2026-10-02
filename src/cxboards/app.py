"""The CXBoards HTTP API, its live event stream, and the built UI.

Local only: the server binds 127.0.0.1, refuses any Host header that isn't
this machine (DNS-rebinding guard), and requires an ``X-CXBoards`` header on
every write, which a cross-site form or fetch can't send without a CORS
preflight this server never grants.

The caller says who it is with ``X-CXBoards-Actor`` (``chris`` from the UI,
``agent`` from the MCP); that is how the UI knows which cards to highlight.
"""

from __future__ import annotations

import asyncio
import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Callable

import httpx
from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import outline
from .config import AUDIO_EXTENSIONS, MAX_IMAGE_BYTES, Config, load_config
from .events import Broadcaster
from .export import Exporter
from .store import Invalid, NotFound, Store
from .unfurl import unfurl as default_unfurl

WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"
ARTIFACTS_ADDRESS = "Muzik/Boards"


def create_app(
    config: Config | None = None,
    unfurl: Callable[[str], dict[str, str]] = default_unfurl,
    export_delay: float = 1.5,
) -> FastAPI:
    config = config or load_config()
    store = Store(config)
    broadcaster = Broadcaster()
    exporter = Exporter(store, delay=export_delay)

    def on_change(board_id: str, rev: int, card_ids: list[str], actor: str) -> None:
        broadcaster.publish({"board_id": board_id, "rev": rev, "card_ids": card_ids, "actor": actor})
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
        for key in ("url", "items", "path"):
            if key in spec:
                data[key] = spec.pop(key)
        if kind == "image" and not data.get("file"):
            if data.get("path"):
                data["file"] = store.import_image_path(data.pop("path"))
            elif data.get("url") or spec.get("image_url"):
                data["file"] = import_image_url(data.pop("url", None) or spec.pop("image_url"))
            else:
                raise Invalid("an image card needs a path or url")
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
        except NotFound:
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
        parent_id = store.resolve_board(parent)["id"] if parent else None
        return store.create_board(body.get("title", ""), body.get("description", ""), parent_id, actor_of(request))

    @app.get("/api/boards/{ref}")
    def get_board(ref: str) -> dict[str, Any]:
        return store.board_state(store.resolve_board(ref)["id"])

    @app.get("/api/boards/{ref}/outline", response_class=PlainTextResponse)
    def get_outline(ref: str) -> str:
        return outline.board_outline(store, store.resolve_board(ref)["id"], config.base_url)

    @app.patch("/api/boards/{board_id}")
    def update_board(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return store.update_board(board_id, body.get("title"), body.get("description"), actor_of(request))

    @app.delete("/api/boards/{board_id}")
    def delete_board(board_id: str, request: Request) -> dict[str, Any]:
        store.delete_board(board_id, actor_of(request))
        exporter.sweep()
        return {"ok": True}

    @app.post("/api/boards/{board_id}/export")
    def export_now(board_id: str) -> dict[str, Any]:
        board = store.resolve_board(board_id)
        path = exporter.export_board(board["id"])
        return {"path": str(path), "artifacts": f"{ARTIFACTS_ADDRESS}/{board['export_slug']}"}

    # ------------------------------------------------------------------ cards

    @app.post("/api/boards/{board_id}/cards")
    def add_card(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        board_id = store.resolve_board(board_id)["id"]
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
        board_id = store.resolve_board(board_id)["id"]
        specs = body.get("cards") or []
        if not isinstance(specs, list) or not specs:
            raise Invalid("send a non-empty list of cards")
        actor = actor_of(request)
        created: list[dict[str, Any]] = []
        with store.batch():  # one revision, one event, one snapshot for the whole batch
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
        for key in ("url", "items", "path"):
            if key in body:
                data[key] = body[key]
        if "url" in data:  # a new link: drop the old preview so nothing stale survives
            data.update(title=None, description=None, image=None, site=None)
        card = store.update_card(
            card_id,
            text=body.get("text"),
            data=data or None,
            color=body.get("color"),
            w=body.get("w"),
            h=body.get("h"),
            actor="system" if set(body) <= {"h"} else actor_of(request),
        )
        if "url" in data:
            after_add([card])
        return card

    @app.post("/api/cards/{card_id}/move")
    def move_card(card_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        card = store.card(card_id)
        target_board = store.resolve_board(body["board"])["id"] if body.get("board") else None
        column = body.get("column", body.get("column_id"))
        column_id = "" if column == "" else resolve_column(card["board_id"], column) if column else None
        return store.move_card(
            card_id,
            x=body.get("x"),
            y=body.get("y"),
            column_id=column_id,
            index=body.get("index"),
            near=body.get("near") or None,
            side=body.get("side") or "right",
            board_id=target_board,
            actor=actor_of(request),
        )

    @app.delete("/api/cards/{card_id}")
    def delete_card(card_id: str, request: Request) -> dict[str, Any]:
        store.delete_card(card_id, actor_of(request))
        return {"ok": True}

    @app.post("/api/boards/{board_id}/arrange")
    def arrange(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        board_id = store.resolve_board(board_id)["id"]
        order = store.arrange(board_id, body.get("card_ids") or None, body.get("mode", "grid"), actor_of(request))
        return {"arranged": order}

    @app.post("/api/boards/{board_id}/group")
    def group(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        board_id = store.resolve_board(board_id)["id"]
        return store.group_into_column(board_id, body.get("card_ids") or [], body.get("title", ""), actor_of(request))

    @app.post("/api/boards/{board_id}/sub-board")
    def sub_board(board_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        board_id = store.resolve_board(board_id)["id"]
        return store.make_sub_board(board_id, body.get("card_ids") or [], body.get("title", ""), actor_of(request))

    # ------------------------------------------------------------------ media

    @app.post("/api/boards/{board_id}/images")
    def upload_image(
        board_id: str,
        request: Request,
        file: UploadFile = File(...),
        x: float | None = Form(None),
        y: float | None = Form(None),
        column: str | None = Form(None),
    ) -> dict[str, Any]:
        board_id = store.resolve_board(board_id)["id"]
        content = file.file.read()
        name = store.save_image_bytes(content, file.filename or "image.png")
        fields: dict[str, Any] = {"data": {"file": name}}
        column_id = resolve_column(board_id, column)
        if column_id:
            fields["column_id"] = column_id
        elif x is not None and y is not None:
            fields.update(x=x, y=y)
        return store.add_card(board_id, "image", actor=actor_of(request), **fields)

    @app.get("/media/{name}")
    def media(name: str) -> FileResponse:
        return FileResponse(store.upload_path(name))

    @app.get("/api/cards/{card_id}/audio")
    def audio(card_id: str) -> Response:
        card = store.card(card_id)
        if card["kind"] != "audio":
            raise NotFound("not an audio card")
        path = Path(card["data"]["path"])
        if path.suffix.lower() not in AUDIO_EXTENSIONS:
            raise NotFound("not an audio file")
        if not path.is_file():
            return JSONResponse({"error": f"{path} isn't reachable (is the drive mounted?)"}, status_code=404)
        return FileResponse(path)

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
