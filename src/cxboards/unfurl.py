"""Link previews and players.

``unfurl`` fetches a preview (oEmbed for YouTube and Spotify, OpenGraph tags
for the rest). ``embed_for`` works out whether a link can play inside its card
(YouTube, Vimeo, Spotify, SoundCloud, Apple Music, Mixcloud, Bandcamp, Google
Maps) and the player URL to load when Chris clicks play.
"""

from __future__ import annotations

import html
import re
from urllib.parse import parse_qs, quote, unquote, urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) CXBoards/0.1"
OEMBED = {
    "youtube.com": "https://www.youtube.com/oembed?format=json&url=",
    "youtu.be": "https://www.youtube.com/oembed?format=json&url=",
    "music.youtube.com": "https://www.youtube.com/oembed?format=json&url=",
    "open.spotify.com": "https://open.spotify.com/oembed?url=",
}
SITE_NAMES = {
    "youtube.com": "YouTube", "youtu.be": "YouTube", "music.youtube.com": "YouTube Music",
    "open.spotify.com": "Spotify", "soundcloud.com": "SoundCloud", "vimeo.com": "Vimeo",
    "music.apple.com": "Apple Music", "mixcloud.com": "Mixcloud",
}


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host


def embed_for(url: str, og_video: str | None = None) -> dict[str, object] | None:
    """The in-card player for a link, or None. ``aspect`` (w/h) or a fixed ``height`` in px."""
    parsed = urlparse(url)
    host = _host(url)
    path = parsed.path
    if host in ("youtube.com", "music.youtube.com", "youtu.be"):
        vid = None
        if host == "youtu.be":
            vid = path.strip("/").split("/")[0]
        elif path.startswith(("/shorts/", "/embed/", "/live/")):
            vid = path.split("/")[2]
        else:
            vid = parse_qs(parsed.query).get("v", [None])[0]
        if vid and re.fullmatch(r"[\w-]{6,20}", vid):
            return {"provider": "YouTube", "src": f"https://www.youtube-nocookie.com/embed/{vid}", "aspect": 16 / 9}
    if host == "vimeo.com":
        match = re.match(r"^/(\d+)", path)
        if match:
            return {"provider": "Vimeo", "src": f"https://player.vimeo.com/video/{match.group(1)}", "aspect": 16 / 9}
    if host == "open.spotify.com":
        match = re.search(r"/(track|album|playlist|episode|show|artist)/([A-Za-z0-9]+)", path)
        if match:
            kind, sid = match.groups()
            height = 152 if kind in ("track", "episode") else 352
            return {"provider": "Spotify", "src": f"https://open.spotify.com/embed/{kind}/{sid}", "height": height}
    if host == "soundcloud.com" and path.count("/") >= 2:
        height = 300 if "/sets/" in path else 166
        src = f"https://w.soundcloud.com/player/?url={quote(url, safe='')}&color=%23e0a33a&visual=false&show_comments=false"
        return {"provider": "SoundCloud", "src": src, "height": height}
    if host == "music.apple.com":
        height = 175 if "i=" in parsed.query else 450
        return {"provider": "Apple Music", "src": f"https://embed.music.apple.com{path}?{parsed.query}".rstrip("?"), "height": height}
    if host == "mixcloud.com" and path.count("/") >= 3:
        return {"provider": "Mixcloud", "src": f"https://www.mixcloud.com/widget/iframe/?hide_cover=1&feed={quote(path, safe='')}", "height": 120}
    if host in ("google.com", "maps.google.com") and ("/maps" in path or host == "maps.google.com"):
        place = re.search(r"/maps/place/([^/]+)", path)
        at = re.search(r"/@(-?\d+\.\d+),(-?\d+\.\d+)", path)
        query = parse_qs(parsed.query).get("q", [None])[0]
        q = unquote(place.group(1)).replace("+", " ") if place else query or (f"{at.group(1)},{at.group(2)}" if at else None)
        if q:
            return {"provider": "Google Maps", "src": f"https://maps.google.com/maps?q={quote(q)}&output=embed", "aspect": 4 / 3}
    if og_video and "bandcamp.com/EmbeddedPlayer" in og_video:
        src = re.sub(r"size=\w+", "size=large", og_video)
        src = re.sub(r"artwork=\w+", "artwork=small", src) if "artwork=" in src else src.rstrip("/") + "/artwork=small/"
        if "tracklist=" not in src:
            src = src.rstrip("/") + "/tracklist=false/"
        return {"provider": "Bandcamp", "src": src.replace("http://", "https://"), "height": 120}
    return None


def _meta(page: str, *names: str) -> str | None:
    for name in names:
        for pattern in (
            rf'<meta[^>]+(?:property|name)=["\']{re.escape(name)}["\'][^>]*content=["\']([^"\']*)["\']',
            rf'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\']{re.escape(name)}["\']',
        ):
            match = re.search(pattern, page, re.IGNORECASE)
            if match and match.group(1).strip():
                return html.unescape(match.group(1).strip())
    return None


def unfurl(url: str, timeout: float = 6.0) -> dict[str, object]:
    """Best-effort preview fields, plus ``embed`` when the link can play in its card. Never raises."""
    host = _host(url)
    out: dict[str, object] = {"site": SITE_NAMES.get(host, host)}
    embed = embed_for(url)
    if embed:
        out["embed"] = embed
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": UA}) as client:
            endpoint = OEMBED.get(host)
            if endpoint:
                resp = client.get(endpoint + quote(url, safe=""))
                if resp.status_code == 200:
                    data = resp.json()
                    for key, field in (("title", "title"), ("thumbnail_url", "image"), ("author_name", "description")):
                        if data.get(key):
                            out[field] = str(data[key])
                    return out
            resp = client.get(url)
            final = str(resp.url)
            if not embed and final != url:
                embed = embed_for(final)  # a short link (maps.app.goo.gl, spoti.fi) that resolves to a player
                if embed:
                    out["embed"] = embed
            if resp.status_code >= 400 or "html" not in resp.headers.get("content-type", ""):
                return out
            page = resp.text[:600_000]
            title = _meta(page, "og:title", "twitter:title")
            if not title:
                match = re.search(r"<title[^>]*>(.*?)</title>", page, re.IGNORECASE | re.DOTALL)
                title = html.unescape(re.sub(r"\s+", " ", match.group(1)).strip()) if match else None
            fields = {
                "title": title,
                "description": _meta(page, "og:description", "twitter:description", "description"),
                "image": _meta(page, "og:image", "twitter:image"),
                "site": _meta(page, "og:site_name") or SITE_NAMES.get(_host(final)),
            }
            for key, value in fields.items():
                if value:
                    out[key] = urljoin(final, value) if key == "image" else value[:400]
            if not embed:
                video = _meta(page, "og:video:secure_url", "og:video:url", "og:video")
                embed = embed_for(final, og_video=video)
                if embed:
                    out["embed"] = embed
    except (httpx.HTTPError, ValueError):
        pass
    return out
