"""Animation cards: pictures that move, every frame drawn with JavaScript.

An animation is code on a card (``data.motion = {code, loop}``): on an ``animation`` card it is the
whole picture; on an ``image`` card it plays over the image (the "Head in the Clouds" cover, clouds
drifting across a still portrait). ``motion/runtime.js`` runs that code: in the board, inside a
sandboxed frame that can only draw (``/motion/runner``), and here, through ``motion/render.mjs``
with a real canvas in Node, to check code before it's saved, to show an agent what it drew
(``sheet``), to make the poster frame that Onyx snapshots and exports show, and to export video.

GUIDE is what Ask and agents read before they make one.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from . import themes

ROOT = Path(__file__).resolve().parents[2] / "motion"
RENDERER = ROOT / "render.mjs"
RUNTIME = ROOT / "runtime.js"
RUNNER = ROOT / "runner.html"

CHECK_SECONDS = 8  # an endless loop in the code is stopped here
RENDER_SECONDS = 90

# The vault's own look (no board theme), as motion palette names.
DEFAULT_PALETTE = {
    "ground": "#FDF6E3",
    "card": "#FFFDF6",
    "ink": "#111111",
    "muted": "#6B6B6B",
    "accent": "#B07A1E",
    "line": "#E0D7B8",
}


class MotionFailed(Exception):
    """The code didn't run: a syntax error, a mistake at run time, or it took too long."""

    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.line = line

    def __str__(self) -> str:
        msg = super().__str__()
        return f"{msg} (line {self.line})" if self.line else msg


def find_node() -> str | None:
    """Node, wherever it is: the LaunchAgent's PATH doesn't include nvm or Homebrew."""
    if os.environ.get("CXBOARDS_NODE"):
        return os.environ["CXBOARDS_NODE"]
    found = shutil.which("node")
    if found:
        return found
    nvm = sorted(
        Path.home().glob(".nvm/versions/node/*/bin/node"),
        key=lambda p: [int(x) for x in p.parts[-3].lstrip("v").split(".") if x.isdigit()],
        reverse=True,
    )
    for candidate in [*nvm, Path("/opt/homebrew/bin/node"), Path("/usr/local/bin/node")]:
        if candidate.is_file():
            return str(candidate)
    return None


def available() -> bool:
    return bool(find_node()) and RENDERER.is_file() and (ROOT / "node_modules" / "@napi-rs" / "canvas").is_dir()


def board_palette(theme: dict[str, Any] | None) -> dict[str, str]:
    """A board's colours under the names drawing code uses (ground, card, ink, muted, accent, line)."""
    tokens = themes.palette(theme)
    if not tokens:
        return dict(DEFAULT_PALETTE)
    return {
        "ground": tokens["canvas"],
        "card": tokens["card"],
        "ink": tokens["ink"],
        "muted": tokens["muted"],
        "accent": tokens["accent"],
        "line": tokens["line"],
    }


def code_hash(code: str, loop: float) -> str:
    return hashlib.sha256(f"{loop}\n{code}".encode()).hexdigest()[:16]


def _run(job: dict[str, Any], timeout: float) -> dict[str, Any]:
    node = find_node()
    if not node or not RENDERER.is_file():
        raise MotionFailed("animations can't be rendered here: Node isn't installed")
    try:
        done = subprocess.run(
            [node, str(RENDERER)], input=json.dumps(job), capture_output=True, text=True, timeout=timeout, cwd=ROOT
        )
    except subprocess.TimeoutExpired:
        raise MotionFailed(f"Stopped: it was still drawing after {timeout:g} seconds (an endless loop?)") from None
    try:
        result = json.loads(done.stdout or "{}")
    except json.JSONDecodeError:
        raise MotionFailed((done.stderr or "the renderer failed").strip().splitlines()[-1][:300]) from None
    if not result.get("ok"):
        raise MotionFailed(result.get("error") or "the renderer failed", result.get("line"))
    return result


def _job(card: dict[str, Any], palette: dict[str, str], image: Path | None, width: float | None = None) -> dict[str, Any]:
    motion = card["data"]["motion"]
    w = float(width or card.get("w") or 360)
    job: dict[str, Any] = {"code": motion["code"], "loop": motion["loop"], "palette": palette, "width": w}
    if card["kind"] == "animation":
        job["height"] = w * float(card["data"].get("aspect") or 0.75)
    if image is not None:
        job["image"] = str(image)
        if card["data"].get("crop"):
            job["crop"] = card["data"]["crop"]
    return job


def check(card: dict[str, Any], palette: dict[str, str], image: Path | None) -> None:
    """Run the code for a dozen frames across its loop; raise MotionFailed on the first problem.
    Without Node it can't be checked here, and the board's sandbox reports errors instead."""
    if not available():
        return
    _run({**_job(card, palette, image), "mode": "check"}, CHECK_SECONDS)


def poster(card: dict[str, Any], palette: dict[str, str], image: Path | None, out: Path) -> Path:
    _run({**_job(card, palette, image), "mode": "poster", "scale": 2, "out": str(out)}, RENDER_SECONDS)
    return out


def sheet(card: dict[str, Any], palette: dict[str, str], image: Path | None) -> bytes:
    """Four frames (0, 27%, 55%, 84% of the loop; uneven, see render.mjs) in one PNG: what an agent looks at to judge its work."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "sheet.png"
        _run({**_job(card, palette, image, width=min(float(card.get("w") or 360), 420)), "mode": "sheet", "scale": 1.5, "out": str(out)}, RENDER_SECONDS)
        return out.read_bytes()


def video(card: dict[str, Any], palette: dict[str, str], image: Path | None, fmt: str, out: Path, loops: int = 2) -> Path:
    """The loop as a video file (mp4 or gif), played ``loops`` times, at twice the card's size."""
    ffmpeg = shutil.which("ffmpeg") or next((p for p in ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg") if Path(p).is_file()), None)
    if not ffmpeg:
        raise MotionFailed("exporting video needs ffmpeg (brew install ffmpeg)")
    fps = 24 if fmt == "mp4" else 15
    with tempfile.TemporaryDirectory() as tmp:
        frames = Path(tmp) / "frames"
        _run({**_job(card, palette, image), "mode": "frames", "scale": 2 if fmt == "mp4" else 1, "fps": fps, "out": str(frames)}, RENDER_SECONDS * 2)
        pattern = str(frames / "frame-%04d.png")
        if fmt == "gif":
            cmd = [ffmpeg, "-v", "error", "-y", "-stream_loop", str(loops - 1), "-framerate", str(fps), "-i", pattern,
                   "-vf", "split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4",
                   "-loop", "0", str(out)]
        else:
            cmd = [ffmpeg, "-v", "error", "-y", "-stream_loop", str(loops - 1), "-framerate", str(fps), "-i", pattern,
                   "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-movflags", "+faststart", str(out)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=RENDER_SECONDS * 2)
        if done.returncode != 0:
            raise MotionFailed(f"ffmpeg: {(done.stderr or '').strip()[-300:]}")
    return out


def runner_html() -> str:
    """The sandboxed page an animation plays in, with the runtime written into it."""
    return RUNNER.read_text().replace("/*RUNTIME*/", RUNTIME.read_text())


# The Content-Security-Policy the runner is served with: scripts may run, and nothing may load or
# connect anywhere. With the iframe's sandbox (no same-origin), a drawing can only draw.
RUNNER_CSP = (
    "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob:; worker-src blob:; "
    "style-src 'unsafe-inline'; img-src blob: data:; base-uri 'none'; form-action 'none'"
)


GUIDE = """\
# Making an animation for a CXBoards board

An animation is a picture that moves, every frame drawn with JavaScript on a canvas: the way
Kevin Ngo (@kevin_t_ngo) makes his. It lives on a card in one of two forms:
- a new **animation card**: the drawing is the whole picture (ink on paper, a little scene), or
- an **image card** brought to life: the image stays and something on it moves, like the
  "Head in the Clouds" album cover where clouds drift across a still portrait.

## 1. Ask first, unless the request already settles it

Before writing any code, ask Chris in ONE short message, offering your best guess for each so a
plain "yes" or "go" is an answer. Ask only what the request and the board don't already settle,
and never more than four:
1. **The one thing that moves, and how.** A gesture, not a scene ("seeds letting go of a dandelion
   and drifting off to the right", "clouds sliding across her face, left to right").
2. **Mood and pace.** Still and slow, an easy drift, restless, or punchy (on a tempo? which BPM?).
3. **Look.** Ink line on paper in the board's colours; brought-to-life over one of the board's
   pictures (name the ones you could use); or bold flat shapes.
4. **Where.** A new card (beside which card?), or over which image.

## 2. Fit the board

Read the board first (read_board) and use what's there: its subject and words, its pictures, its
theme. Draw in env.palette (the board's own colours: ground, card, ink, muted, accent, line) unless
Chris asks otherwise, so it looks like it belongs. Take motifs from the board's titles and notes.

## 3. The style that works (from Kevin Ngo's pieces)

- One subject and a lot of empty paper. One gesture, not a busy scene.
- Thin, dark ink lines that wobble a little and "boil" (redraw ~10×/s), as if drawn by hand: the
  pen does this for you. pen.paper() gives the board's ground with a little grain.
- Small details carry it: a dotted trail, a tiny star, a line that draws itself
  (pen.path(points, {draw: k}) with k going 0→1).
- Motion has weight: ease in and out (ease.inOut, ease.out); only drift is linear.
- It loops seamlessly. Drive everything from p (0→1 over the loop): whatever moves is back where it
  started at p = 1. Use Math.sin(TAU * p), ease.wave(p) (0→1→0), or (start + p) % 1 for things that
  travel across and wrap around. 4–10 second loops. Nothing flashes or strobes.
- Over a picture: keep it (cover() draws it) and add ONE living element: clouds drifting, light
  moving, rain, a glow breathing, birds crossing. The artwork itself is alive; don't bury it.

## 4. The code

The code defines `function draw(env)` and, if it needs one, `function setup(env)` (run once; its
return value is env.state). Frames are drawn at ~30 fps. env holds:
- ctx, w, h: a 2D canvas context and the size in CSS pixels (already scaled for the screen)
- t (seconds), p (0..1 through the loop), loop (seconds), frame
- palette: {ground, card, ink, muted, accent, line} (hex), state (what setup returned)
- image (the card's picture, or null) and cover(image?, {zoom, dx, dy}) → draws it cover-fit and
  returns its {x, y, w, h}
- pen, the hand-drawn marks (o = options; color defaults to palette.ink):
  - pen.line(x1, y1, x2, y2, o), pen.path(points, o) with o.closed / o.draw (0..1)
  - pen.circle(x, y, r, o) (o.draw, o.sweep), pen.arc(x, y, r, a0, a1, o), pen.dot(x, y, r, o)
  - pen.fill(points, o) (o.color, o.stroke), pen.text(str, x, y, {size, align, color})
  - pen.blob(x, y, r, {color, alpha, softness}): a soft glow or puff
  - pen.cloud(x, y, size, {seed, light, shade, glow, alpha, puffs}): a painted cumulus
  - pen.paper({color, grain}), pen.grain(amount): paper texture over what's drawn
  - common o: width (1.6), alpha, wobble (1.1 px), passes (2 = a sketchier double line)
- noise(x, y, z) → -1..1 (smooth), rand(seed) → a seeded 0..1 generator
- ease.inOut / out / in / wave / bounce, TAU, lerp, clamp, rgba(hex, alpha)
It runs in a sandbox: no DOM, no network, no images except env.image. Keep it under ~150 lines.

Example, ink on paper (a dandelion letting its seeds go):

    function setup({ w, h, rand }) {
      const r = rand(4)
      return { cx: w * 0.5, cy: h * 0.4,
        seeds: Array.from({ length: 24 }, (_, i) => ({ a: (i / 24) * TAU, len: 30 + r() * 8, d: r() })) }
    }
    function draw({ pen, w, h, p, t, state, noise, ease, clamp }) {
      pen.paper()
      const { cx, cy, seeds } = state
      const sway = noise(t * 0.4, 1) * 5
      pen.path([[w * 0.5, h * 0.95], [w * 0.5 + sway * 0.4, h * 0.7], [cx + sway, cy + 5]])
      seeds.forEach((s, i) => {
        const k = clamp((p - (i / seeds.length) * 0.55) / 0.3)       // each lets go in turn
        const away = ease.out(k) * (p > 0.9 ? 1 - (p - 0.9) / 0.1 : 1) // and they're home at p = 1
        const x = cx + sway + Math.cos(s.a) * s.len + away * (w * 0.55 + s.d * 60)
        const y = cy + Math.sin(s.a) * s.len - away * (50 + s.d * 70)
        pen.dot(x, y, 1.6)
        if (away < 0.15) pen.line(cx + sway, cy, x, y, { width: 0.8 })
      })
      pen.circle(cx + sway, cy, 4.5, { width: 1.2 })
    }

Example, over an image card (clouds drifting across the picture):

    function draw({ pen, w, h, p, cover, noise }) {
      cover()
      for (let i = 0; i < 4; i++) {
        const x = ((i / 4 + p) % 1) * (w + 300) - 150      // wraps around: seamless
        pen.cloud(x, h * (0.2 + 0.15 * i) + noise(i, p * 2) * 8, 55 + 15 * (i % 3), { seed: i + 1, alpha: 0.85 })
      }
      pen.grain(0.04)
    }

## 5. Look at it before you show it

Make it (add_cards with kind "animation", or animate(card) on an image), then call
preview_animation(card) and LOOK at the four frames. Check: is the subject clear and well placed?
Does it fit the board's colours? Does frame 4 lead back into frame 1 (the loop)? Is anything
clipped, too busy or too faint? Fix it with animate(card, code) and look again; two rounds is
normal. Then tell Chris what you made in one line.
"""


def guide(board: dict[str, Any] | None = None, cards: list[dict[str, Any]] | None = None) -> str:
    """GUIDE, plus the board's colours and pictures when there is one."""
    if not board:
        return GUIDE
    pal = board_palette(board.get("theme"))
    lines = [GUIDE, f"## This board: {board['title']} ({board['id']})", ""]
    lines.append("env.palette here: " + ", ".join(f"{k} {v}" for k, v in pal.items()))
    theme = (board.get("theme") or {}).get("preset", "vault")
    lines.append(f"theme: {theme}")
    pictures = [c for c in cards or [] if c["kind"] == "image"]
    if pictures:
        lines.append("Pictures you could bring to life (animate(card, code)):")
        for c in pictures[:20]:
            animated = " (already animated)" if c["data"].get("motion") else ""
            lines.append(f"- {c['id']}: {c['text'] or 'no caption'}{animated}")
    moving = [c for c in cards or [] if c["kind"] == "animation"]
    if moving:
        lines.append("Animations already on it: " + ", ".join(f"{c['id']} ({c['text'] or 'untitled'})" for c in moving))
    return "\n".join(lines)
