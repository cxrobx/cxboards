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
from fastapi import Body, FastAPI, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import chat as chatlib
from . import formats, outline, themes
from . import templates as library
from .fonts import FontCache, FontError, google_fetch
from . import motion as motionlib
from .layout import DEFAULT_WIDTH
from .config import AUDIO_EXTENSIONS, MAX_FILE_BYTES, MAX_IMAGE_BYTES, VIDEO_EXTENSIONS, Config, load_config
from .events import Broadcaster
from .export import Exporter
from .locate import locate as default_locate
from .store import PATH_KINDS, Invalid, NotFound, Store, slugify
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
    templates_root: Path | None = None,
    font_fetch: Callable[[str], tuple[int, bytes]] = google_fetch,
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
        exporter.sweep()  # snapshots of boards no longer in Onyx (or gone while the server was down)
        yield
        # Turns still answering are stopped, so each saves what it had as "stopped".
        running = [t.task for t in list(turns.values()) if t.task]
        for task in running:
            task.cancel()
        if running:
            await asyncio.wait(running, timeout=10)
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

    @app.exception_handler(library.TemplateError)
    async def broken_library(request: Request, exc: library.TemplateError) -> JSONResponse:
        return JSONResponse({"error": f"the template library has a problem: {exc}"}, status_code=500)

    fonts = FontCache(config.home, font_fetch)

    @app.exception_handler(FontError)
    async def bad_font(request: Request, exc: FontError) -> JSONResponse:
        return JSONResponse({"error": str(exc)}, status_code=400)

    def with_fonts(theme: Any) -> Any:
        """Fetch a theme's Google fonts before it's saved or previewed: a font that doesn't exist is refused."""
        try:
            normalized = themes.normalize(theme)
        except themes.ThemeError as exc:
            raise Invalid(str(exc)) from exc
        for family in themes.families(normalized):
            fonts.ensure(family)
        return theme

    @app.get("/fonts/css")
    def font_css(family: list[str] = Query(default=[])) -> Response:
        return Response(fonts.css(family[:4]), media_type="text/css", headers={"Cache-Control": "max-age=86400"})

    @app.get("/fonts/file/{name}")
    def font_file(name: str) -> Response:
        path = fonts.file(name)
        if path is None:
            raise NotFound("no such font file")
        return FileResponse(path, headers={"Cache-Control": "max-age=31536000, immutable", "Access-Control-Allow-Origin": "*"})

    def templates_now() -> library.Catalog:
        return library.catalog(templates_root or library.ROOT)

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
        if kind == "animation" or (kind == "image" and (spec.get("code") or data.get("motion"))):
            if spec.get("code") is not None:
                data["motion"] = {"code": spec.get("code"), "loop": spec.get("loop") or 6}
            if spec.get("aspect") is not None:
                data["aspect"] = spec["aspect"]
            if kind == "animation" and not data.get("motion"):
                raise Invalid("an animation card needs code (a function draw(env))")
            check_motion({"kind": kind, "data": data, "w": out.get("w") or DEFAULT_WIDTH[kind], "board_id": board_id})
        return out

    # ------------------------------------------------------------------ animations (motion.py)

    def motion_context(card: dict[str, Any]) -> tuple[dict[str, str], Path | None]:
        # The theme the board wears: its own, or (with none of its own) its project's.
        worn, _ = store.effective_theme(card["board_id"])
        image = store.upload_path(card["data"]["file"]) if card["kind"] == "image" else None
        return motionlib.board_palette(worn), image

    def check_motion(card: dict[str, Any]) -> None:
        """Run new drawing code before it's saved, so a broken animation never reaches the board."""
        motion = card["data"].get("motion")
        if not motion:
            return
        normalized = {**card, "data": {**card["data"], "motion": store._motion(motion)}}
        palette, image = motion_context(normalized)
        try:
            motionlib.check(normalized, palette, image)
        except motionlib.MotionFailed as exc:
            raise Invalid(f"the animation doesn't run: {exc}") from exc

    def make_poster(card_id: str) -> None:
        """The still that Onyx snapshots, exports and the print view show for an animation."""
        try:
            card = store.card(card_id)
            motion = card["data"].get("motion")
            if not motion or not motionlib.available():
                return
            palette, image = motion_context(card)
            key = motionlib.code_hash(motion["code"] + json.dumps(palette, sort_keys=True), motion["loop"])
            if motion.get("poster_of") == key:
                return
            out = config.home / f".poster-{card_id}.png"
            try:
                motionlib.poster(card, palette, image, out)
                name = store.save_image_bytes(out.read_bytes(), "poster.png")
            finally:
                out.unlink(missing_ok=True)
            fresh = store.card(card_id)["data"].get("motion") or {}
            if fresh.get("code") == motion["code"]:  # unless it was changed meanwhile
                store.update_card(card_id, data={"motion": {**fresh, "poster": name, "poster_of": key}}, actor="system")
        except (NotFound, Invalid, motionlib.MotionFailed, OSError):
            pass

    def after_motion(cards: list[dict[str, Any]]) -> None:
        for card in cards:
            if card["data"].get("motion"):
                threading.Thread(target=make_poster, args=(card["id"],), daemon=True).start()

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
        after_motion(cards)

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
        # A template from the library (templates/<category>/<slug>.yaml), or a board made a template.
        found = templates_now().get(template) if template and not str(template).startswith("b_") else None
        if found:
            return store.build_board(
                body.get("title") or found.name, library.plan(found.cards), parent_id, actor_of(request),
                folder=bool(body.get("folder")), theme=found.theme, description=body.get("description", ""),
            )
        template_id = board_id_of(template) if template else None
        return store.create_board(
            body.get("title", ""), body.get("description", ""), parent_id, actor_of(request), template_id=template_id,
            folder=bool(body.get("folder")),
        )

    # Sidebar sections (store.sections). Other windows hear about a change as a board-less event,
    # which makes them reload the sidebar.
    def sections_changed() -> None:
        broadcaster.publish({"board_id": None, "sections": True, "card_ids": [], "actor": "chris"})

    @app.get("/api/sections")
    def list_sections() -> list[dict[str, Any]]:
        return store.sections()

    @app.post("/api/sections")
    def add_section(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        parent = body.get("parent_id")
        section = store.add_section(board_id_of(parent) if parent else None, body.get("at"), body.get("title", ""))
        sections_changed()
        return section

    @app.patch("/api/sections/{section_id}")
    def update_section(section_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        fields = {k: body[k] for k in ("title", "at") if k in body}
        if "parent_id" in body:
            fields["parent_id"] = board_id_of(body["parent_id"]) if body["parent_id"] else None
        section = store.update_section(section_id, **fields)
        sections_changed()
        return section

    @app.delete("/api/sections/{section_id}")
    def delete_section(section_id: str) -> dict[str, Any]:
        section = store.delete_section(section_id)
        sections_changed()
        return section

    @app.get("/api/templates")
    def list_templates(q: str = "", category: str = "") -> dict[str, Any]:
        """The library: categories (with counts) and the templates matching ``q`` / ``category``."""
        cat = templates_now()
        return {
            "categories": [{**c, "count": len(cat.in_category(c["slug"]))} for c in cat.categories],
            "templates": [t.summary() for t in library.search(cat, q, category)],
            "problems": cat.problems,  # files left out until they're fixed
        }

    @app.get("/api/templates/{slug}")
    def get_template(slug: str) -> dict[str, Any]:
        found = templates_now().get(slug)
        if not found:
            raise NotFound(f"no template called {slug}")
        return {**found.summary(), "cards": found.cards}

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
            is_template=body.get("is_template"), in_onyx=body.get("in_onyx"), theme=with_fonts(body["theme"]) if "theme" in body else ...,
        )

    @app.post("/api/boards/{board_id}/move")
    def move_board(board_id: str, request: Request, body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
        """``parent``: the board to nest it in (id or title); leave out or null for top level."""
        parent = body.get("parent")
        return store.move_board(board_id_of(board_id), board_id_of(parent) if parent else None, actor_of(request))

    @app.get("/api/themes")
    def theme_catalog() -> list[dict[str, Any]]:
        return themes.catalog()

    @app.post("/api/themes/preview")
    def theme_preview(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        try:
            return {"palette": themes.palette(themes.normalize(with_fonts(body.get("theme"))))}
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
        # Rendered beside Onyx's folder, not into it: printing doesn't put a board in Onyx.
        page = exporter.write(board["id"], config.home / "print").read_text(encoding="utf-8")
        script = "<script>addEventListener('load',()=>setTimeout(()=>print(),400))</script>"
        page = page.replace("<head>", f'<head><base href="/print/{board["id"]}/">', 1).replace("</body>", script + "</body>")
        page = page.replace("@media screen and (prefers-color-scheme: dark)", "@media not all")  # print on paper colours
        return HTMLResponse(page)

    @app.get("/print/{board_id}/media/{name}")
    def print_media(board_id: str, name: str) -> FileResponse:
        board = store.resolve_board(board_id)
        path = config.home / "print" / board["export_slug"] / "media" / name
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

    @app.get("/api/cards/{card_id}")
    def get_card(card_id: str) -> dict[str, Any]:
        return store.card(card_id)

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
        if data.get("motion"):
            current = store.card(card_id)
            check_motion({**current, "data": {**current["data"], **data}})
        if text is not None and HEX.match(text) and store.card(card_id)["kind"] == "note":
            kind, data, text = "swatch", {**data, "hex": text.strip()}, ""
        card = store.update_card(
            card_id,
            text=text,
            data=data or None,
            color=body.get("color"),
            w=body.get("w"),
            h=body.get("h"),
            x=body.get("x"),
            y=body.get("y"),
            locked=body.get("locked"),
            z=body.get("z"),
            kind=kind,
            actor="system" if set(body) <= {"h"} else actor_of(request),
        )
        if "url" in data:
            after_add([card])
        if data.get("motion"):
            after_motion([card])
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

    @app.post("/api/uploads/from-path")
    def upload_from_path(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """An image on disk copied in without making a card (a Finder drop on Ask)."""
        name = store.import_image_path(str(body.get("path", "")))
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

    @app.post("/api/cards/{card_id}/motion")
    def set_motion(card_id: str, request: Request, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """Bring an image card to life, or change an animation: {code, loop}. Empty code takes the
        animation off an image card. The code is run first, and refused if it doesn't run."""
        card = store.card(card_id)
        if card["kind"] not in ("image", "animation"):
            raise Invalid("only an image card or an animation card can move")
        code = str(body.get("code") or "")
        if not code.strip():
            if card["kind"] == "animation":
                raise Invalid("an animation card needs code; delete the card to remove it")
            return store.update_card(card_id, data={"motion": None}, actor=actor_of(request))
        old = card["data"].get("motion") or {}
        motion = {"code": code, "loop": body.get("loop") or old.get("loop") or 6}
        data: dict[str, Any] = {"motion": motion}
        if card["kind"] == "animation" and body.get("aspect"):
            data["aspect"] = body["aspect"]
        check_motion({**card, "data": {**card["data"], **data}})
        updated = store.update_card(card_id, data=data, actor=actor_of(request))
        after_motion([updated])
        return updated

    @app.post("/api/cards/{card_id}/motion/error")
    def motion_error(card_id: str, body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        """The board's sandbox hit an error the server's check didn't (kept on the card, so Ask
        and agents can see and fix it). Not an edit of Chris's: it folds into the step before."""
        card = store.card(card_id)
        motion = card["data"].get("motion")
        message = str(body.get("message") or "")[:500]
        if not motion or motion.get("error") == message or (motion.get("error") is None and not message):
            return card
        return store.update_card(card_id, data={"motion": {**motion, "error": message or None}}, actor="system")

    previews: dict[str, bytes] = {}

    @app.get("/api/cards/{card_id}/motion/preview")
    def motion_preview(card_id: str) -> Response:
        """Four frames of the animation in one PNG (what an agent looks at to judge its work)."""
        card = store.card(card_id)
        if not card["data"].get("motion"):
            raise Invalid("this card doesn't move")
        palette, image = motion_context(card)
        key = card_id + motionlib.code_hash(card["data"]["motion"]["code"] + json.dumps(palette, sort_keys=True) + str(card["w"]), card["data"]["motion"]["loop"])
        if key not in previews:
            try:
                previews[key] = motionlib.sheet(card, palette, image)
            except motionlib.MotionFailed as exc:
                raise Invalid(f"the animation doesn't run: {exc}") from exc
            while len(previews) > 32:
                previews.pop(next(iter(previews)))
        return Response(previews[key], media_type="image/png", headers={"Cache-Control": "no-cache"})

    @app.get("/api/cards/{card_id}/motion/export.{fmt}")
    def motion_export(card_id: str, fmt: str) -> FileResponse:
        """The animation as a video to post: mp4, or a gif. Made once per version of the code."""
        if fmt not in ("mp4", "gif"):
            raise Invalid("export an animation as mp4 or gif")
        card = store.card(card_id)
        motion = card["data"].get("motion")
        if not motion:
            raise Invalid("this card doesn't move")
        palette, image = motion_context(card)
        renders = config.home / "renders"
        renders.mkdir(exist_ok=True)
        stem = slugify(card["text"] or store.board(card["board_id"])["title"])[:60] or "animation"
        out = renders / f"{stem}-{motionlib.code_hash(motion['code'] + json.dumps(palette, sort_keys=True), motion['loop'])}.{fmt}"
        if not out.is_file():
            try:
                motionlib.video(card, palette, image, fmt, out)
            except motionlib.MotionFailed as exc:
                raise Invalid(f"couldn't make the video: {exc}") from exc
        return FileResponse(out, filename=f"{stem}.{fmt}", media_type="video/mp4" if fmt == "mp4" else "image/gif")

    @app.get("/api/motion/guide", response_class=PlainTextResponse)
    def motion_guide(board: str = "") -> str:
        if not board:
            return motionlib.guide()
        board_id = board_id_of(board)
        return motionlib.guide({**store.board(board_id), "theme": store.effective_theme(board_id)[0]}, store.cards(board_id))

    @app.get("/motion/runner", response_class=HTMLResponse)
    def motion_runner() -> HTMLResponse:
        """Where an animation plays: sandboxed by the board's iframe, and by this policy."""
        return HTMLResponse(
            motionlib.runner_html(),
            headers={"Content-Security-Policy": motionlib.RUNNER_CSP, "Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"},
        )

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

    # Turns run as jobs (chatlib.Turn), one per chat at a time, so leaving the board or closing
    # the panel doesn't end one. These handlers are async on purpose: they read `turns` on the
    # event loop, where a turn's last steps (save the answer, leave `turns`) can't interleave.
    turns: dict[str, chatlib.Turn] = {}

    @app.get("/api/boards/{board_id}/chats")
    async def list_chats(board_id: str) -> list[dict[str, Any]]:
        return [{**c, "running": c["id"] in turns} for c in store.chats(board_id_of(board_id))]

    @app.get("/api/chats/{chat_id}")
    async def get_chat(chat_id: str) -> dict[str, Any]:
        return {**store.chat(chat_id), "running": chat_id in turns}

    @app.delete("/api/chats/{chat_id}")
    async def delete_chat(chat_id: str) -> dict[str, Any]:
        if chat_id in turns:
            raise Invalid("that chat is still answering: stop it first")
        store.delete_chat(chat_id)
        return {"ok": True}

    def sse(turn: chatlib.Turn) -> StreamingResponse:
        async def stream():
            async for kind, data in turn.follow():
                yield f"event: {kind}\ndata: {json.dumps(data)}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    async def run_turn(turn: chatlib.Turn, binary: str | None, cmd: list[str], model: str) -> None:
        text: list[str] = []
        tools: list[str] = []
        outcome: dict[str, Any] = {"stopped": True}
        try:
            if not binary:
                note = "Claude Code isn't installed (no `claude` on this Mac), so Ask can't answer."
                outcome = {"error": note}
                turn.push("error", {"message": note})
                return
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
                    turn.push(kind, event)
        except asyncio.CancelledError:
            turn.push("stopped", {})  # Stop, or the server shutting down; the process is gone
        finally:
            answer = {"role": "assistant", "text": "".join(text).strip(), "model": model, **outcome}
            if binary:
                answer["tools"] = tools
            store.add_message(turn.chat_id, answer)
            turns.pop(turn.chat_id, None)
            turn.finish()

    @app.post("/api/boards/{board_id}/chat")
    async def ask(board_id: str, body: dict[str, Any] = Body(...)) -> StreamingResponse:
        """Start a turn and watch it: chat, token, tool, then done | error | stopped (server-sent
        events). Closing this stream only stops watching; the turn goes on."""
        board = store.resolve_board(board_id)
        message = str(body.get("message") or "").strip()
        images = [str(n) for n in body.get("images") or []]
        for name in images:
            store.upload_path(name)  # 404 for anything that isn't an upload
            if Path(name).suffix.lower() not in chatlib.IMAGE_TYPES:
                raise Invalid("Ask can look at PNG, JPEG, GIF and WebP pictures")
        if not message and not images:
            raise Invalid("ask something")
        if body.get("chat_id") in turns:
            raise Invalid("still answering the last question: wait, or stop it")
        model = body.get("model") if body.get("model") in chatlib.MODELS else chatlib.DEFAULT_MODEL
        title = message or ("A picture" if len(images) == 1 else f"{len(images)} pictures")
        chat_id = body.get("chat_id") or store.start_chat(board["id"], title)
        history = store.chat(chat_id)["messages"]
        state = store.board_state(board["id"])
        by_id = {c["id"]: c for c in state["cards"]}
        picked = [by_id[i] for i in body.get("selection") or [] if i in by_id]
        store.add_message(chat_id, {"role": "user", "text": message, "selection": [c["id"] for c in picked],
                                    **({"images": images} if images else {})})
        binary = claude()
        cmd: list[str] = []
        if binary:
            system = chatlib.system_prompt(
                outline.board_outline(store, board["id"], config.base_url),
                [outline.card_line(c) for c in picked],
            )
            cmd = chatlib.build_cmd(
                binary, chatlib.user_prompt(message, history, images, config.uploads_dir), system, model,
                chatlib.mcp_config(config.home, config.base_url), config.uploads_dir,
            )
        turn = chatlib.Turn(chat_id, board["id"])
        turn.push("chat", {"chat_id": chat_id})
        turns[chat_id] = turn
        turn.task = asyncio.create_task(run_turn(turn, binary, cmd, model))
        return sse(turn)

    @app.get("/api/chats/{chat_id}/live")
    async def watch_chat(chat_id: str) -> StreamingResponse:
        """A running turn from its start, then live; an empty stream if the chat isn't answering."""
        turn = turns.get(chat_id)
        if turn is None:
            store.chat(chat_id)  # 404 for a chat that doesn't exist
            turn = chatlib.Turn(chat_id, "")
            turn.finish()
        return sse(turn)

    @app.post("/api/chats/{chat_id}/stop")
    async def stop_chat(chat_id: str) -> dict[str, Any]:
        turn = turns.get(chat_id)
        if turn is None or turn.task is None:
            return {"ok": False}
        turn.task.cancel()
        return {"ok": True}

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

    @app.get("/api/version")
    def version() -> dict[str, Any]:
        """Which build of the UI the server is serving. It changes with every `npm run build` (the
        page names its hashed bundle), so an open window can tell it's running an older one."""
        page = WEB_DIST / "index.html"
        build = hashlib.sha1(page.read_bytes()).hexdigest()[:12] if page.is_file() else None
        return {"build": build}

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
