"""Per-board themes: a preset or custom colours, and the full palette the app wears for it.

A theme names three colours (ground, ink, accent), a font and corners, and can go further: a
second accent, its own card and line colours, any Google Fonts family for headings and for body
text (fetched once and served locally by fonts.py), a background image from the board's uploads
under a tinted scrim, and print or film grain. Everything
else the app paints with (card, fill, lines, muted text, glow, shadow) is derived
here, the same way Onyx derives its chrome from a vault theme: muted text is mixed
from the ink toward the ground only as far as it stays readable, and an accent too
faint on the ground falls back to the ink. So no custom combination can leave a
label unreadable.

The server is the one place palettes are computed: the board state carries its
palette, the picker previews presets and custom choices through it, and the Onyx
snapshot is coloured from it. A board with no theme of its own wears its nearest parent's
(Store.effective_theme), so one theme dresses a whole project. "vault" said explicitly is the app's
own look even inside a themed project; it follows the Mac's light/dark setting, and every other
theme is fixed light or dark.
"""

from __future__ import annotations

import re
from typing import Any

HEX = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")
FAMILY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ]{0,40}$")  # a Google Fonts family name
UPLOAD = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,120}$")  # a file in the uploads folder
GRAIN = ("none", "print", "film")

FONTS = {
    "mono": {"body": '"JetBrains Mono", "SF Mono", ui-monospace, Menlo, monospace', "display": None, "weight": 400},
    "sans": {"body": '"Poppins", system-ui, -apple-system, sans-serif', "display": None, "weight": 400},
    "serif": {"body": '"Iowan Old Style", "Palatino", Georgia, serif', "display": '"Fraunces", Georgia, serif', "weight": 400},
    "chrisx": {"body": '"Poppins", system-ui, sans-serif', "display": '"Fraunces", Georgia, serif', "weight": 300},
}
CORNERS = {"round": ("8px", "10px"), "square": ("0px", "0px")}

PRESETS: dict[str, dict[str, Any]] = {
    "vault": {"label": "Vault", "note": "CXBoards' own look; follows light and dark"},
    "chrisx": {
        "label": "Chris X", "note": "chrisx.art: black, cream, Fraunces, square",
        "ground": "#000000", "ink": "#F3ECDD", "accent": "#F3ECDD", "font": "chrisx", "corners": "square",
        # DESIGN.md: cards are the same black as the canvas, defined by cream hairlines.
        "fixed": {"card": "#000000", "muted": "#A89E89", "line": "#3A3833"},
    },
    "film": {
        "label": "Film", "note": "Tungsten amber on warm black",
        "ground": "#18130E", "ink": "#EDE3CF", "accent": "#E8A04F", "font": "sans", "corners": "round",
    },
    "studio": {
        "label": "Studio Night", "note": "Charcoal and lamp-light amber",
        "ground": "#15171A", "ink": "#D9D4C7", "accent": "#E0A33A", "font": "mono", "corners": "round",
    },
    "paper": {
        "label": "Paper", "note": "White, black, a blue pen",
        "ground": "#FFFFFF", "ink": "#161616", "accent": "#2563EB", "font": "sans", "corners": "round",
    },
    "midnight": {
        "label": "Midnight", "note": "Deep navy, cool light",
        "ground": "#0E1626", "ink": "#DCE3EE", "accent": "#7CC4FA", "font": "sans", "corners": "round",
    },
    "sage": {
        "label": "Sage", "note": "Pale green, forest ink",
        "ground": "#EDF1E8", "ink": "#1E2A1F", "accent": "#4D7C0F", "font": "serif", "corners": "round",
    },
    "rose": {
        "label": "Rose", "note": "Blush and deep rose",
        "ground": "#FBF0F1", "ink": "#2B1B21", "accent": "#C0396B", "font": "serif", "corners": "round",
    },
}


class ThemeError(ValueError):
    pass


def _hex(value: Any, what: str) -> str:
    match = HEX.match(str(value or "").strip())
    if not match:
        raise ThemeError(f"{what} must be a hex colour like #E0A33A")
    h = match.group(1)
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return "#" + h.upper()


def _number(value: Any, what: str, lo: float, hi: float, default: float) -> float:
    if value in (None, ""):
        return default
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ThemeError(f"{what} is a number from {lo} to {hi}") from None
    if not lo <= n <= hi:
        raise ThemeError(f"{what} is a number from {lo} to {hi}")
    return round(n, 3)


def _fonts(value: Any) -> dict[str, Any] | None:
    """{display, body, display_style, display_weight, body_weight}: Google Fonts families."""
    if not value:
        return None
    if not isinstance(value, dict):
        raise ThemeError("fonts is {display, body} with Google Fonts family names")
    out: dict[str, Any] = {}
    for key in ("display", "body"):
        name = " ".join(str(value.get(key) or "").split())
        if name:
            if not FAMILY.match(name):
                raise ThemeError(f"{key} font {name!r} isn't a font family name")
            out[key] = name
    if not out:
        return None
    style = value.get("display_style", "normal")
    if style not in ("normal", "italic"):
        raise ThemeError("display_style is normal or italic")
    out["display_style"] = style
    out["display_weight"] = int(_number(value.get("display_weight"), "display_weight", 100, 900, 400))
    out["body_weight"] = int(_number(value.get("body_weight"), "body_weight", 100, 900, 400))
    return out


def _backdrop(value: Any) -> dict[str, Any] | None:
    """{file, dim, blur, tint, tint_strength}: an uploaded image under the canvas."""
    if not value:
        return None
    if not isinstance(value, dict) or not UPLOAD.match(str(value.get("file") or "")):
        raise ThemeError("backdrop is {file: an uploaded image's file name, dim, blur, tint}")
    out = {
        "file": value["file"],
        "dim": _number(value.get("dim"), "backdrop dim", 0, 0.95, 0.72),
        "blur": _number(value.get("blur"), "backdrop blur", 0, 24, 0),
        "tint_strength": _number(value.get("tint_strength"), "tint_strength", 0, 0.8, 0),
    }
    if value.get("tint"):
        out["tint"] = _hex(value["tint"], "backdrop tint")
    return out


def families(theme: dict[str, Any] | None) -> list[str]:
    """The Google Fonts families a theme needs."""
    fonts = (theme or {}).get("fonts") or {}
    return list(dict.fromkeys(f for f in (fonts.get("display"), fonts.get("body")) if f))


def normalize(theme: Any) -> dict[str, Any] | None:
    """A stored theme: None (no theme of its own: wear the parent's), {"preset": "vault"} (the app's own
    look, said on purpose), {"preset": name}, or custom {ground, ink, accent, font, corners} with the
    optional accent2, card, line, fonts, backdrop and grain."""
    if theme in (None, ""):
        return None
    if theme == "vault" or (isinstance(theme, dict) and theme.get("preset") == "vault"):
        return {"preset": "vault"}
    if isinstance(theme, str):
        theme = {"preset": theme}
    if not isinstance(theme, dict):
        raise ThemeError("a theme is a preset name or {ground, ink, accent, font, corners}")
    preset = theme.get("preset", "custom")
    if preset != "custom":
        if preset not in PRESETS:
            raise ThemeError(f"no theme called {preset!r}; try one of {', '.join(PRESETS)} or custom colours")
        return {"preset": preset}
    font = theme.get("font", "mono")
    corners = theme.get("corners", "round")
    if font not in FONTS:
        raise ThemeError(f"font is one of {', '.join(FONTS)}")
    if corners not in CORNERS:
        raise ThemeError("corners are round or square")
    out: dict[str, Any] = {
        "preset": "custom",
        "ground": _hex(theme.get("ground"), "ground"),
        "ink": _hex(theme.get("ink"), "ink"),
        "accent": _hex(theme.get("accent") or theme.get("ink"), "accent"),
        "font": font,
        "corners": corners,
    }
    for key in ("accent2", "card", "line"):
        if theme.get(key):
            out[key] = _hex(theme[key], key)
    fonts = _fonts(theme.get("fonts"))
    if fonts:
        out["fonts"] = fonts
    backdrop = _backdrop(theme.get("backdrop"))
    if backdrop:
        out["backdrop"] = backdrop
    grain = theme.get("grain") or "none"
    if grain not in GRAIN:
        raise ThemeError(f"grain is one of {', '.join(GRAIN)}")
    if grain != "none":
        out["grain"] = grain
    return out


# ---------------------------------------------------------------- colour maths

def _rgb(hex_: str) -> tuple[float, float, float]:
    h = hex_.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))  # type: ignore[return-value]


def _hexof(rgb: tuple[float, float, float]) -> str:
    return "#" + "".join(f"{round(max(0.0, min(1.0, c)) * 255):02X}" for c in rgb)


def mix(a: str, b: str, t: float) -> str:
    """t of the way from a to b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hexof(tuple(x + (y - x) * t for x, y in zip(ra, rb)))  # type: ignore[arg-type]


def luminance(hex_: str) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in _rgb(hex_))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _readable_toward(ink: str, ground: str, minimum: float) -> str:
    """The ink mixed as far toward the ground as it can go and still read at ``minimum``."""
    best = ink
    for step in range(1, 20):
        candidate = mix(ink, ground, step / 20)
        if contrast(candidate, ground) < minimum:
            break
        best = candidate
    return best


# ---------------------------------------------------------------- the palette

def _stack(family: str, role: str) -> str:
    """A Google family with a fallback of its own kind, so the page reads the same while it loads."""
    low = family.lower()
    if any(k in low for k in ("mono", "courier", "code", "typewriter", "elite")):
        tail = '"Courier New", ui-monospace, monospace'
    elif any(k in low for k in ("serif", "garamond", "playfair", "fraunces", "lora", "baskerville", "bodoni", "caslon", "didot", "spectral", "cormorant", "crimson", "libre")) and "sans" not in low:
        tail = "Georgia, serif"
    elif role == "display" and any(k in low for k in ("anton", "bebas", "oswald", "league gothic", "condensed")):
        tail = '"Impact", "Arial Narrow", sans-serif'
    else:
        tail = "system-ui, -apple-system, sans-serif"
    return f'"{family}", {tail}'


def fonts_href(names: list[str]) -> str:
    """Where the page loads a theme's fonts from: our own cached copy (fonts.py), never Google directly."""
    from urllib.parse import quote
    return "/fonts/css?" + "&".join("family=" + quote(n) for n in names) if names else ""


def palette(theme: dict[str, Any] | None) -> dict[str, str] | None:
    """The app's CSS tokens for a theme; None for vault (the app's own look)."""
    if theme is None or theme.get("preset") == "vault":
        return None
    if theme.get("preset") == "custom":
        spec = theme
        fixed: dict[str, str] = {}
    else:
        spec = PRESETS[theme["preset"]]
        fixed = spec.get("fixed", {})
        if "ground" not in spec:
            return None
    ground, ink = spec["ground"], spec["ink"]
    if contrast(ground, ink) < 4.5:
        # Custom colours that can't be read against each other: black or white ink, whichever reads
        # better, and if even that falls short (a mid grey), the ground eases away from it until it reads.
        ink = max(("#000000", "#FFFFFF"), key=lambda c: contrast(c, ground))
        away = "#FFFFFF" if ink == "#000000" else "#000000"
        for step in range(1, 11):
            if contrast(ground, ink) >= 4.5:
                break
            ground = mix(spec["ground"], away, step / 10)
    dark = luminance(ground) < luminance(ink)
    accent = spec["accent"] if contrast(spec["accent"], ground) >= 2.2 else ink
    accent2 = spec.get("accent2") or accent
    accent2 = accent2 if contrast(accent2, ground) >= 2.2 else accent
    font = dict(FONTS[spec["font"]])
    google = spec.get("fonts") or {}
    if google.get("body"):
        font["body"] = _stack(google["body"], "body")
        font["weight"] = google.get("body_weight", 400)
    if google.get("display"):
        font["display"] = _stack(google["display"], "display")
    radius, radius_lg = CORNERS[spec["corners"]]
    tokens = {
        "scheme": "dark" if dark else "light",
        "canvas": ground,
        "ground": mix(ground, ink, 0.035),
        "card": mix(ground, ink, 0.07) if dark else mix(ground, "#FFFFFF", 0.6),
        "fill": mix(ground, ink, 0.1 if dark else 0.07),
        "line": mix(ground, ink, 0.2 if dark else 0.16),
        "lineInk": mix(ground, ink, 0.45),
        "ink": ink,
        "muted": _readable_toward(ink, ground, 4.6),
        "accent": accent,
        "onAccent": "#111111" if luminance(accent) > 0.35 else "#FFFFFF",
        "glow": accent + ("66" if dark else "59"),
        "shadow": ("0 1px 2px rgba(0,0,0,.45), 0 10px 24px -16px rgba(0,0,0,.9)" if dark
                   else "0 1px 2px rgba(0,0,0,.05), 0 10px 24px -16px rgba(0,0,0,.28)"),
        "font": font["body"],
        "fontDisplay": font["display"] or font["body"],
        "fontWeight": str(font["weight"]),
        "radius": radius,
        "radiusLg": radius_lg,
        "accent2": accent2,
        "fontsHref": fonts_href(families(spec)),
        # Only a theme with its own heading font sets how headings sit; others keep the app's.
        "displayStyle": google.get("display_style", "normal") if google.get("display") else "",
        "displayWeight": str(google.get("display_weight", 400)) if google.get("display") else "",
        "grain": spec.get("grain", "none"),
        "backdrop": "",
        "backdropDim": "0",
        "backdropBlur": "0px",
        "backdropScrim": ground,
    }
    # Its own card and line colours, if it names them; a card the text can't be read on is ignored.
    if spec.get("card") and contrast(spec["card"], ink) >= 4.5:
        tokens["card"] = spec["card"]
    if spec.get("line"):
        tokens["line"] = spec["line"]
    backdrop = spec.get("backdrop")
    if backdrop:
        tint = backdrop.get("tint")
        tokens.update(
            backdrop="/media/" + backdrop["file"],
            backdropDim=f"{backdrop['dim']:.3f}",
            backdropBlur=f"{backdrop['blur']:g}px",
            backdropScrim=mix(ground, tint, backdrop["tint_strength"]) if tint else ground,
        )
    tokens.update(fixed)
    return tokens


def catalog() -> list[dict[str, Any]]:
    """Every preset with its palette, for the picker."""
    out = []
    for name, spec in PRESETS.items():
        theme = None if name == "vault" else {"preset": name}
        out.append({"name": name, "label": spec["label"], "note": spec["note"], "palette": palette(theme)})
    return out


def label(theme: dict[str, Any] | None) -> str:
    if theme is None or theme.get("preset") == "vault":
        return "Vault"
    if theme.get("preset") == "custom":
        return f"Custom ({theme['ground']} / {theme['ink']} / {theme['accent']})"
    return PRESETS[theme["preset"]]["label"]
