"""Google Fonts, fetched once and served from CXBoards' own home, so a theme's fonts work offline
and in Onyx snapshots (which load them from :4870 like their audio).

``ensure(family)`` asks Google for the family (regular, bold and italic where it has them, falling
back to whatever it does have), downloads every font file the stylesheet names, and keeps a copy
of the stylesheet pointing at our ``/fonts/file/<name>`` instead. A family Google doesn't know is
refused with a sentence, which is how a theme with a mistyped font name is turned away.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import httpx

from .themes import FAMILY

# Google serves woff2 to a modern browser; it decides by the User-Agent.
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Safari/605.1.15"
VARIANTS = ("ital,wght@0,400;0,700;1,400;1,700", "wght@400;700", "")
URL = re.compile(r"url\((https://fonts\.gstatic\.com/[^)]+)\)")


class FontError(ValueError):
    pass


def google_fetch(url: str) -> tuple[int, bytes]:
    resp = httpx.get(url, headers={"User-Agent": UA}, timeout=20, follow_redirects=True)
    return resp.status_code, resp.content


class FontCache:
    def __init__(self, home: Path, fetch: Callable[[str], tuple[int, bytes]] = google_fetch) -> None:
        self.dir = home / "fonts"
        self.fetch = fetch

    def _css_path(self, family: str) -> Path:
        return self.dir / (re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-") + ".css")

    def ensure(self, family: str) -> str:
        """The local stylesheet for ``family``, fetching it the first time."""
        family = " ".join(family.split())
        if not FAMILY.match(family):
            raise FontError(f"{family!r} isn't a font family name")
        path = self._css_path(family)
        if path.is_file():
            return path.read_text()
        css = None
        for variant in VARIANTS:
            spec = quote(family) + (f":{variant}" if variant else "")
            try:
                status, body = self.fetch(f"https://fonts.googleapis.com/css2?family={spec}&display=swap")
            except httpx.HTTPError as exc:
                raise FontError(f"couldn't reach Google Fonts for {family!r} ({exc.__class__.__name__})") from exc
            if status == 200:
                css = body.decode("utf-8")
                break
        if css is None:
            raise FontError(f"Google Fonts has no family called {family!r}")
        self.dir.mkdir(parents=True, exist_ok=True)

        def local(match: re.Match[str]) -> str:
            src = match.group(1)
            name = hashlib.sha1(src.encode()).hexdigest()[:16] + Path(src.split("?")[0]).suffix
            target = self.dir / name
            if not target.is_file():
                status, body = self.fetch(src)
                if status != 200:
                    raise FontError(f"couldn't download a file of {family!r}")
                target.write_bytes(body)
            return f"url(/fonts/file/{name})"

        css = URL.sub(local, css)
        path.write_text(css)
        return css

    def css(self, families: list[str]) -> str:
        return "\n".join(self.ensure(f) for f in families)

    def file(self, name: str) -> Path | None:
        if not re.fullmatch(r"[0-9a-f]{16}\.(woff2|woff|ttf|otf)", name):
            return None
        path = self.dir / name
        return path if path.is_file() else None
