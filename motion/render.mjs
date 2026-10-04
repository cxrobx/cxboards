// Renders an animation card on the server with a real canvas (@napi-rs/canvas), for
// src/cxboards/motion.py. Reads one JSON job on stdin and prints one JSON result on stdout.
//
//   mode "check"   run setup and a dozen frames across the loop; report the first error
//   mode "poster"  one PNG at phase `at` (default 0.25) → out
//   mode "sheet"   a 2×2 contact sheet at phases 0, ¼, ½, ¾ → out (what an agent looks at)
//   mode "frames"  every frame of one loop at `fps` → out/frame-0001.png… (for ffmpeg)
//
// job: { mode, code, loop, width, height, scale, palette, image (a file path or null), out, at, fps }
// The caller enforces the time limit (an endless loop in the code is killed from outside).

import { createCanvas, loadImage } from '@napi-rs/canvas'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'
import './runtime.js'

const { CXMotion } = globalThis

function reply(result) {
  process.stdout.write(JSON.stringify(result))
}

async function main() {
  const job = JSON.parse(readFileSync(0, 'utf8'))
  let image = job.image ? await loadImage(job.image) : null
  if (image && job.crop) {
    // The card shows only its crop (percentages of the picture), so the animation sees only that.
    const { x, y, w, h } = job.crop
    const sx = (image.width * x) / 100, sy = (image.height * y) / 100
    const sw = Math.max(1, (image.width * w) / 100), sh = Math.max(1, (image.height * h) / 100)
    const cropped = createCanvas(Math.round(sw), Math.round(sh))
    cropped.getContext('2d').drawImage(image, sx, sy, sw, sh, 0, 0, cropped.width, cropped.height)
    image = cropped
  }
  const width = Math.round(job.width || 360)
  // An image card is as tall as its picture is at this width; an animation card says its own height.
  const height = Math.round(job.height || (image ? (width * image.height) / image.width : width * 0.75))
  const scale = job.scale || 1

  function stage(w = width, h = height, s = scale) {
    const canvas = createCanvas(Math.round(w * s), Math.round(h * s))
    const ctx = canvas.getContext('2d')
    const motion = CXMotion.create({
      ctx, width: w, height: h, scale: s, palette: job.palette, image, code: job.code, loop: job.loop,
      makeCanvas: (cw, ch) => createCanvas(cw, ch),
    })
    return { canvas, ctx, motion }
  }

  try {
    if (job.mode === 'check') {
      const { motion } = stage(width, height, 1)
      for (let i = 0; i < 12; i++) motion.frame((motion.loop * i) / 12)
      return reply({ ok: true })
    }
    if (job.mode === 'poster') {
      const { canvas, motion } = stage()
      motion.frame(motion.loop * (job.at ?? 0.25))
      writeFileSync(job.out, canvas.toBuffer('image/png'))
      return reply({ ok: true, files: [job.out] })
    }
    if (job.mode === 'sheet') {
      const { canvas, motion } = stage()
      const pad = 12 * scale, label = 22 * scale
      const cw = canvas.width, ch = canvas.height
      const sheet = createCanvas(cw * 2 + pad * 3, (ch + label) * 2 + pad * 3)
      const s = sheet.getContext('2d')
      s.fillStyle = '#2b2b2b'
      s.fillRect(0, 0, sheet.width, sheet.height)
      s.font = `${13 * scale}px sans-serif`
      const phases = [0, 0.25, 0.5, 0.75]
      phases.forEach((p, i) => {
        motion.frame(motion.loop * p)
        const x = pad + (i % 2) * (cw + pad)
        const y = pad + Math.floor(i / 2) * (ch + label + pad)
        s.fillStyle = '#ddd'
        s.fillText(`t = ${(motion.loop * p).toFixed(2)}s  (${Math.round(p * 100)}% through the loop)`, x, y + 15 * scale)
        s.drawImage(canvas, x, y + label)
      })
      writeFileSync(job.out, sheet.toBuffer('image/png'))
      return reply({ ok: true, files: [job.out] })
    }
    if (job.mode === 'frames') {
      const { canvas, motion } = stage()
      const fps = job.fps || 24
      const count = Math.max(1, Math.round(motion.loop * fps))
      mkdirSync(job.out, { recursive: true })
      for (let i = 0; i < count; i++) {
        motion.frame(i / fps)
        writeFileSync(join(job.out, `frame-${String(i + 1).padStart(4, '0')}.png`), canvas.toBuffer('image/png'))
      }
      return reply({ ok: true, count })
    }
    reply({ ok: false, error: `unknown mode ${job.mode}` })
  } catch (e) {
    reply({ ok: false, error: e.message || String(e), line: e.line ?? null })
  }
}

main().catch((e) => reply({ ok: false, error: e.message || String(e) }))
