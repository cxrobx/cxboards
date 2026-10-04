// CXBoards motion runtime: draws an animation's frames from its code.
//
// The same file runs in two places: the board's sandboxed frame (in a worker, on an
// OffscreenCanvas) and render.mjs on the server (the check before a card is saved, previews for
// agents, poster frames, video export). It knows nothing about either: it is handed a 2D context,
// a size, the board's palette and an optional image, and asked for frames.
//
// An animation's code defines `function draw(env)` (and optionally `function setup(env)`, run once,
// whose return value is env.state). env holds:
//   ctx, w, h          the 2D context, sized in CSS pixels (already scaled for the screen)
//   t, p, loop, frame  seconds, phase 0..1 through the loop, the loop's length, the frame number
//   palette            the board's colours: ground, card, ink, muted, accent, line (hex strings)
//   image, cover()     the card's picture (or null) and a helper that draws it cover-fit
//   pen                hand-drawn marks: line, path, circle, arc, dot, fill, blob, cloud, grain, paper, text
//   noise(x, y, z)     smooth noise, -1..1     rand(seed)  a seeded 0..1 generator
//   ease               inOut, out, in, wave(p) (0→1→0 over a loop), bounce
//   TAU, lerp, clamp, rgba(hex, alpha)
;(function (root) {
  'use strict'

  const TAU = Math.PI * 2

  // ------------------------------------------------------------------ randomness and noise

  function rand(seed) {
    let a = (seed >>> 0) || 1
    return function () {
      a = (a + 0x6d2b79f5) | 0
      let t = Math.imul(a ^ (a >>> 15), 1 | a)
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296
    }
  }

  // Improved Perlin noise in three dimensions, seeded.
  function makeNoise(seed) {
    const r = rand(seed)
    const p = new Uint8Array(512)
    const base = Array.from({ length: 256 }, (_, i) => i)
    for (let i = 255; i > 0; i--) {
      const j = Math.floor(r() * (i + 1))
      ;[base[i], base[j]] = [base[j], base[i]]
    }
    for (let i = 0; i < 512; i++) p[i] = base[i & 255]
    const fade = (t) => t * t * t * (t * (t * 6 - 15) + 10)
    const mix = (a, b, t) => a + t * (b - a)
    const grad = (h, x, y, z) => {
      const u = (h & 15) < 8 ? x : y
      const v = (h & 15) < 4 ? y : (h & 15) === 12 || (h & 15) === 14 ? x : z
      return ((h & 1) ? -u : u) + ((h & 2) ? -v : v)
    }
    return function noise(x, y = 0, z = 0) {
      const X = Math.floor(x) & 255, Y = Math.floor(y) & 255, Z = Math.floor(z) & 255
      x -= Math.floor(x); y -= Math.floor(y); z -= Math.floor(z)
      const u = fade(x), v = fade(y), w = fade(z)
      const A = p[X] + Y, AA = p[A] + Z, AB = p[A + 1] + Z
      const B = p[X + 1] + Y, BA = p[B] + Z, BB = p[B + 1] + Z
      return mix(
        mix(mix(grad(p[AA], x, y, z), grad(p[BA], x - 1, y, z), u), mix(grad(p[AB], x, y - 1, z), grad(p[BB], x - 1, y - 1, z), u), v),
        mix(mix(grad(p[AA + 1], x, y, z - 1), grad(p[BA + 1], x - 1, y, z - 1), u), mix(grad(p[AB + 1], x, y - 1, z - 1), grad(p[BB + 1], x - 1, y - 1, z - 1), u), v),
        w,
      )
    }
  }

  // ------------------------------------------------------------------ small helpers

  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x))
  const lerp = (a, b, t) => a + (b - a) * t

  function rgba(hex, alpha = 1) {
    const h = String(hex || '#000').replace('#', '')
    const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h.slice(0, 6)
    const n = parseInt(full, 16) || 0
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`
  }

  const ease = {
    inOut: (t) => (t < 0.5 ? 2 * t * t : 1 - Math.pow(-2 * t + 2, 2) / 2),
    out: (t) => 1 - Math.pow(1 - t, 3),
    in: (t) => t * t * t,
    wave: (p) => 0.5 - 0.5 * Math.cos(TAU * p),
    bounce: (t) => {
      const n = 7.5625, d = 2.75
      if (t < 1 / d) return n * t * t
      if (t < 2 / d) return n * (t -= 1.5 / d) * t + 0.75
      if (t < 2.5 / d) return n * (t -= 2.25 / d) * t + 0.9375
      return n * (t -= 2.625 / d) * t + 0.984375
    },
  }

  // ------------------------------------------------------------------ the pen

  // Marks that look drawn by hand: every stroke wobbles a little, and the wobble re-draws itself a
  // few times a second ("line boil"), as in hand-drawn animation. A stroke's wobble is keyed to its
  // order in draw(), so the same stroke boils the same way every loop.
  function makePen(ctx, world) {
    let id = 0
    const n = world.noise

    function wobble(points, amount, closed) {
      const k = id++
      const boil = world.boil
      return points.map(([x, y], i) => {
        const s = closed && i === points.length - 1 ? 0 : i // a closed loop meets itself
        return [
          x + amount * n(k * 7.13 + 0.5, s * 0.31, boil * 1.7),
          y + amount * n(k * 3.71 + 40.5, s * 0.31, boil * 1.7),
        ]
      })
    }

    function along(points, step = 7) {
      const out = []
      for (let i = 0; i < points.length - 1; i++) {
        const [x1, y1] = points[i], [x2, y2] = points[i + 1]
        const steps = Math.max(1, Math.ceil(Math.hypot(x2 - x1, y2 - y1) / step))
        for (let s = 0; s < steps; s++) out.push([lerp(x1, x2, s / steps), lerp(y1, y2, s / steps)])
      }
      out.push(points[points.length - 1])
      return out
    }

    function trace(points, closed) {
      ctx.beginPath()
      ctx.moveTo(points[0][0], points[0][1])
      for (let i = 1; i < points.length - 1; i++) {
        const [x, y] = points[i], [nx, ny] = points[i + 1]
        ctx.quadraticCurveTo(x, y, (x + nx) / 2, (y + ny) / 2)
      }
      const last = points[points.length - 1]
      ctx.lineTo(last[0], last[1])
      if (closed) ctx.closePath()
    }

    function stroke(points, o = {}, closed = false) {
      if (points.length < 2) return
      const passes = o.passes ?? 1
      ctx.save()
      ctx.lineCap = 'round'
      ctx.lineJoin = 'round'
      ctx.strokeStyle = o.color ?? world.palette.ink
      for (let pass = 0; pass < passes; pass++) {
        ctx.globalAlpha = (o.alpha ?? 1) * (pass ? 0.45 : 1)
        ctx.lineWidth = (o.width ?? 1.6) * (pass ? 0.7 : 1)
        trace(wobble(along(points, o.step ?? 7), o.wobble ?? 1.1, closed), closed)
        ctx.stroke()
      }
      ctx.restore()
    }

    const pen = {
      line(x1, y1, x2, y2, o = {}) {
        stroke([[x1, y1], [x2, y2]], o)
      },
      // Through points; o.closed joins the end to the start; o.draw (0..1) draws only that much of
      // it, for a line that draws itself.
      path(points, o = {}) {
        let pts = points.map((q) => [q[0] ?? q.x, q[1] ?? q.y])
        if (pts.length < 2) return
        if (o.closed) pts = [...pts, pts[0]]
        if (o.draw !== undefined) {
          const all = along(pts, 2)
          pts = all.slice(0, Math.max(2, Math.round(all.length * clamp(o.draw))))
        }
        stroke(pts, o, o.closed && o.draw === undefined)
      },
      // A hand-drawn circle: it runs a little past where it started, and isn't quite round.
      circle(x, y, r, o = {}) {
        const k = id
        const start = o.start ?? n(k * 1.3, 9.1) * Math.PI
        const sweep = TAU * (o.sweep ?? 1.06) * (o.draw ?? 1)
        const count = Math.max(12, Math.ceil((r * Math.abs(sweep)) / 6))
        const pts = []
        for (let i = 0; i <= count; i++) {
          const a = start + (sweep * i) / count
          const rr = r * (1 + (o.wobble ?? 1) * 0.035 * n(k * 2.1, i * 0.18))
          pts.push([x + Math.cos(a) * rr, y + Math.sin(a) * rr])
        }
        stroke(pts, { ...o, step: 999 })
      },
      arc(x, y, r, a0, a1, o = {}) {
        const count = Math.max(6, Math.ceil((r * Math.abs(a1 - a0)) / 6))
        const pts = []
        for (let i = 0; i <= count; i++) {
          const a = a0 + ((a1 - a0) * i) / count
          pts.push([x + Math.cos(a) * r, y + Math.sin(a) * r])
        }
        stroke(pts, { ...o, step: 999 })
      },
      dot(x, y, r = 1.6, o = {}) {
        const k = id++
        ctx.save()
        ctx.globalAlpha = o.alpha ?? 1
        ctx.fillStyle = o.color ?? world.palette.ink
        ctx.beginPath()
        ctx.arc(x + 0.4 * n(k, world.boil), y + 0.4 * n(k + 9, world.boil), r, 0, TAU)
        ctx.fill()
        ctx.restore()
      },
      // A filled shape with a wobbly edge (o.stroke also outlines it).
      fill(points, o = {}) {
        const pts = points.map((q) => [q[0] ?? q.x, q[1] ?? q.y])
        if (pts.length < 3) return
        const shape = wobble(along([...pts, pts[0]], 8), o.wobble ?? 0.8, true)
        ctx.save()
        ctx.globalAlpha = o.alpha ?? 1
        ctx.fillStyle = o.color ?? world.palette.accent
        trace(shape, true)
        ctx.fill()
        ctx.restore()
        if (o.stroke) stroke([...pts, pts[0]], { ...o, color: o.stroke }, true)
      },
      // A soft round glow: light, smoke, a puff of cloud.
      blob(x, y, r, o = {}) {
        if (!(r > 0)) return
        const c = o.color ?? '#FFFFFF'
        const g = ctx.createRadialGradient(x, y, 0, x, y, r)
        const a = o.alpha ?? 0.8
        g.addColorStop(0, rgba(c, a))
        g.addColorStop(clamp(1 - (o.softness ?? 0.6), 0, 0.99), rgba(c, a * 0.85))
        g.addColorStop(1, rgba(c, 0))
        ctx.save()
        ctx.fillStyle = g
        ctx.beginPath()
        ctx.arc(x, y, r, 0, TAU)
        ctx.fill()
        ctx.restore()
      },
      // A painterly cloud of soft puffs, lit from above (o.seed picks its shape; o.light, o.shade,
      // o.alpha, o.puffs).
      // A cumulus is a flat-ish base with rounded bumps piled on top: puffs are placed along a
      // dome, big in the middle and small at the edges, each shaded underneath and lit on top.
      cloud(x, y, size, o = {}) {
        const r = rand((o.seed ?? 1) * 9973)
        const puffs = o.puffs ?? 16
        const light = o.light ?? '#FFFFFF'
        const shade = o.shade ?? '#9FB0C8'
        const alpha = o.alpha ?? 0.95
        const parts = []
        for (let i = 0; i < puffs; i++) {
          const u = (i + r() * 0.6) / puffs // left to right along the cloud
          const across = (u - 0.5) * 2 // -1..1
          const dome = Math.sqrt(Math.max(0, 1 - across * across))
          const pr = size * (0.16 + 0.22 * dome) * (0.8 + r() * 0.45)
          const px = x + across * size * 1.15
          const py = y - dome * size * 0.42 * r() - pr * 0.2
          parts.push([px, py, pr])
        }
        // the base: a long soft shadow the puffs sit on
        pen.blob(x, y + size * 0.12, size * 1.2, { color: shade, alpha: alpha * 0.35, softness: 0.85 })
        for (const [px, py, pr] of parts) pen.blob(px, py + pr * 0.35, pr * 1.08, { color: shade, alpha: alpha * 0.7, softness: 0.4 })
        for (const [px, py, pr] of parts) pen.blob(px, py, pr, { color: light, alpha, softness: 0.3 })
        // a little light caught on the tops
        for (const [px, py, pr] of parts) pen.blob(px - pr * 0.2, py - pr * 0.35, pr * 0.55, { color: o.glow ?? '#FFF8E8', alpha: alpha * 0.5, softness: 0.7 })
      },
      // Paper texture over everything drawn so far (amount 0..1; ~0.05 is subtle).
      grain(amount = 0.05) {
        const tile = world.grainTile()
        if (!tile) return
        ctx.save()
        ctx.globalAlpha = amount
        ctx.globalCompositeOperation = 'multiply'
        ctx.fillStyle = ctx.createPattern(tile, 'repeat')
        ctx.fillRect(0, 0, world.w, world.h)
        ctx.restore()
      },
      // The board's ground with a little grain: a sheet to draw on.
      paper(o = {}) {
        ctx.save()
        ctx.fillStyle = o.color ?? world.palette.ground
        ctx.fillRect(0, 0, world.w, world.h)
        ctx.restore()
        pen.grain(o.grain ?? 0.04)
      },
      text(str, x, y, o = {}) {
        ctx.save()
        ctx.globalAlpha = o.alpha ?? 1
        ctx.fillStyle = o.color ?? world.palette.ink
        ctx.font = `${o.weight ?? 400} ${o.size ?? 16}px ${o.font ?? world.palette.font ?? 'Georgia, serif'}`
        ctx.textAlign = o.align ?? 'left'
        ctx.textBaseline = o.baseline ?? 'alphabetic'
        ctx.fillText(String(str), x + 0.5 * n(id++, world.boil), y)
        ctx.restore()
      },
    }
    pen.reset = () => {
      id = 0
    }
    return pen
  }

  // ------------------------------------------------------------------ compile and run

  class MotionError extends Error {
    constructor(message, line) {
      super(message)
      this.line = line ?? null
    }
  }

  // The line in the card's code a stack points at. V8 and JavaScriptCore word stacks differently,
  // so this is a best effort; the message is what matters.
  function lineOf(err) {
    const m = String((err && err.stack) || '').match(/(?:<anonymous>|anonymous|Function code):(\d+):\d+/)
    return m ? Math.max(1, Number(m[1]) - 2) : null
  }

  function compile(code) {
    const body =
      String(code || '') +
      '\n;return { setup: typeof setup === "function" ? setup : null, draw: typeof draw === "function" ? draw : null }'
    let made
    try {
      // The stateless helpers are plain names in the code too, so `TAU` works without taking it
      // from env (a setup that used it bare failed with "TAU is not defined").
      made = new Function('TAU', 'lerp', 'clamp', 'rgba', 'ease', 'rand', body)(TAU, lerp, clamp, rgba, ease, rand)
    } catch (e) {
      throw new MotionError(`${e.name}: ${e.message}`, lineOf(e))
    }
    if (!made.draw) throw new MotionError('The code needs a function draw(env).')
    return made
  }

  // opts: ctx, width, height, scale, palette, image, code, loop, seed, boil (line-boil fps),
  // makeCanvas(w, h) (for the grain tile).
  function create(opts) {
    const fns = compile(opts.code)
    const world = {
      w: opts.width,
      h: opts.height,
      scale: opts.scale || 1,
      palette: Object.assign(
        { ground: '#FDF6E3', card: '#FFFDF6', ink: '#111111', muted: '#6B6B6B', accent: '#B07A1E', line: '#E0D7B8' },
        opts.palette || {},
      ),
      noise: makeNoise(opts.seed || 7),
      boil: 0,
      tile: undefined,
      grainTile() {
        if (world.tile !== undefined) return world.tile
        world.tile = null
        if (!opts.makeCanvas) return null
        const c = opts.makeCanvas(128, 128)
        const g = c.getContext('2d')
        const img = g.createImageData(128, 128)
        const r = rand(11)
        for (let i = 0; i < img.data.length; i += 4) {
          const v = 128 + Math.floor(r() * 127)
          img.data[i] = img.data[i + 1] = img.data[i + 2] = v
          img.data[i + 3] = 255
        }
        g.putImageData(img, 0, 0)
        world.tile = c
        return c
      },
    }
    const ctx = opts.ctx
    const loop = Math.max(0.5, Number(opts.loop) || 6)
    const boilFps = opts.boil ?? 10
    const pen = makePen(ctx, world)
    let image = opts.image || null
    let frameNo = 0

    function cover(img = image, o = {}) {
      if (!img) return null
      const iw = img.width, ih = img.height
      const s = Math.max(world.w / iw, world.h / ih) * (o.zoom ?? 1)
      const dw = iw * s, dh = ih * s
      const dx = (world.w - dw) / 2 + (o.dx ?? 0), dy = (world.h - dh) / 2 + (o.dy ?? 0)
      ctx.drawImage(img, dx, dy, dw, dh)
      return { x: dx, y: dy, w: dw, h: dh, scale: s }
    }

    const env = {
      ctx, pen, noise: world.noise, rand, ease, TAU, lerp, clamp, rgba, cover,
      get w() { return world.w },
      get h() { return world.h },
      get palette() { return world.palette },
      get image() { return image },
      loop, t: 0, p: 0, frame: 0, state: undefined,
    }

    function run(fn) {
      try {
        return fn(env)
      } catch (e) {
        if (e instanceof MotionError) throw e
        throw new MotionError(`${(e && e.name) || 'Error'}: ${(e && e.message) || e}`, lineOf(e))
      }
    }

    let ready = false
    function frame(t) {
      env.t = t
      env.p = (((t % loop) + loop) % loop) / loop
      env.frame = frameNo++
      world.boil = Math.floor(t * boilFps)
      ctx.setTransform(world.scale, 0, 0, world.scale, 0, 0)
      ctx.clearRect(0, 0, world.w, world.h)
      pen.reset()
      if (!ready) {
        ready = true
        if (fns.setup) env.state = run(fns.setup)
      }
      ctx.save()
      run(fns.draw)
      ctx.restore()
    }

    return {
      frame,
      loop,
      resize(width, height, scale) {
        world.w = width
        world.h = height
        world.scale = scale || world.scale
        if (fns.setup) env.state = run(fns.setup)
      },
      setImage(img) {
        image = img || null
      },
      setPalette(palette) {
        Object.assign(world.palette, palette || {})
      },
    }
  }

  root.CXMotion = { create, compile, MotionError, version: 1 }
})(typeof globalThis !== 'undefined' ? globalThis : self)
