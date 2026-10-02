"""Link previews: oEmbed for YouTube and Spotify, OpenGraph tags for the rest."""

from __future__ import annotations

import html
import re
from urllib.parse import quote, urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/605.1.15 (KHTML, like Gecko) CXBoards/0.1"
OEMBED = {
    "youtube.com": "https://www.youtube.com/oembed?format=json&url=",
    "youtu.be": "https://www.youtube.com/oembed?format=json&url=",
    "open.spotify.com": "https://open.spotify.com/oembed?url=",
}
SITE_NAMES = {"youtube.com": "YouTube", "youtu.be": "YouTube", "open.spotify.com": "Spotify"}


def _host(url: str) -> str:
    host = (urlparse(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


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


def unfurl(url: str, timeout: float = 6.0) -> dict[str, str]:
    """Best-effort preview fields. Never raises; returns what it could find."""
    host = _host(url)
    out: dict[str, str] = {"site": SITE_NAMES.get(host, host)}
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
                "site": _meta(page, "og:site_name"),
            }
            for key, value in fields.items():
                if value:
                    out[key] = urljoin(str(resp.url), value) if key == "image" else value[:400]
    except (httpx.HTTPError, ValueError):
        pass
    return out
