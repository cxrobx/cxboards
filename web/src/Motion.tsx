// Animation cards on the board: drawing code (data.motion) played in a sandboxed frame.
//
// The frame is /motion/runner (motion/runner.html): <iframe sandbox="allow-scripts"> without
// same-origin, served with a policy that allows no loads or connections, so the code can only draw.
// It plays in a worker where the browser allows, with a watchdog. Here we size it, hand it the
// board's colours and the card's picture, and decide when it plays: only on screen, not when the
// board is zoomed far out, at most MAX_PLAYING at once, and under Reduce Motion only while hovered.

import { useStore } from '@xyflow/react'
import { useEffect, useRef, useState } from 'react'
import type { Card } from './api'

const MAX_PLAYING = 6
const MIN_ZOOM = 0.3

/** The board's colours as drawing code knows them (the theme's CSS tokens). */
export function boardPalette(): Record<string, string> {
  const css = getComputedStyle(document.documentElement)
  const get = (name: string, fallback: string) => css.getPropertyValue(name).trim() || fallback
  return {
    ground: get('--canvas', '#fdf6e3'),
    card: get('--card', '#fffdf6'),
    ink: get('--ink', '#111111'),
    muted: get('--muted', '#6b6b6b'),
    accent: get('--amber', '#b07a1e'),
    accent2: get('--accent-2', '') || get('--amber', '#b07a1e'),
    line: get('--line', '#e0d7b8'),
    font: get('--font', 'Georgia, serif'),
  }
}

// Which layers may play: every layer says whether it wants to, the first MAX_PLAYING get to.
type Layer = { wants: () => boolean; set: (on: boolean) => void }
const layers: Layer[] = []
function schedule() {
  let n = 0
  for (const layer of layers) {
    const on = layer.wants() && n < MAX_PLAYING
    if (on) n++
    layer.set(on)
  }
}

const reduced = () => window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false

async function pictureFor(card: Card): Promise<ImageBitmap | null> {
  if (card.kind !== 'image' || !card.data.file) return null
  const blob = await fetch(`/media/${card.data.file}`).then((r) => r.blob())
  const full = await createImageBitmap(blob)
  const crop = card.data.crop
  if (!crop) return full
  const sx = (full.width * crop.x) / 100
  const sy = (full.height * crop.y) / 100
  const sw = Math.max(1, (full.width * crop.w) / 100)
  const sh = Math.max(1, (full.height * crop.h) / 100)
  const cropped = await createImageBitmap(full, sx, sy, sw, sh)
  full.close()
  return cropped
}

/** An animated card's drawing code, to read or change by hand (Ask can change it too). */
export function MotionEditor({ card, onClose, onSaved }: { card: Card; onClose: () => void; onSaved: (c: Card) => void }) {
  const motion = card.data.motion ?? { code: '', loop: 6 }
  const [code, setCode] = useState<string>(motion.code)
  const [loop, setLoop] = useState<number>(motion.loop)
  const [error, setError] = useState<string | null>(motion.error ?? null)
  const [busy, setBusy] = useState(false)
  const [frames, setFrames] = useState<string | null>(null)

  const save = async () => {
    setBusy(true)
    setError(null)
    try {
      const resp = await fetch(`/api/cards/${card.id}/motion`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CXBoards': '1' },
        body: JSON.stringify({ code, loop }),
      })
      const body = await resp.json()
      if (!resp.ok) throw new Error(body.error ?? resp.statusText)
      onSaved(body)
      setFrames(`/api/cards/${card.id}/motion/preview?v=${Date.now()}`)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel dialog motion-editor" onKeyDown={(e) => e.key === 'Escape' && onClose()}>
        <header>
          <h2>Animation code</h2>
          <label className="muted">
            loop{' '}
            <input className="field loop" type="number" min={1} max={60} step={0.5} value={loop} onChange={(e) => setLoop(Number(e.target.value))} />{' '}
            s
          </label>
          <button className="ghost" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="dialog-body">
          <textarea
            className="field code"
            spellCheck={false}
            value={code}
            onChange={(e) => setCode(e.target.value)}
            onKeyDown={(e) => {
              e.stopPropagation()
              if (e.key === 's' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                void save()
              }
            }}
          />
          {error && <p className="motion-error-text">⚠ {error}</p>}
          {frames && <img className="motion-frames" src={frames} alt="Four frames of the loop" />}
          <p className="muted">
            Defines <code>draw(env)</code>; the drawing kit (pen, palette, noise, ease…) is in{' '}
            <a href="/api/motion/guide" target="_blank" rel="noreferrer">
              the guide
            </a>
            . ⌘S saves: the code is run first and refused if it doesn't run.
          </p>
        </div>
        <footer>
          <a className="ghost" href={`/api/cards/${card.id}/motion/export.gif`} download>
            GIF
          </a>
          <a className="ghost" href={`/api/cards/${card.id}/motion/export.mp4`} download>
            MP4
          </a>
          <button className="primary" disabled={busy} onClick={() => void save()}>
            {busy ? 'Checking…' : 'Save'}
          </button>
        </footer>
      </div>
    </div>
  )
}

function hash(text: string): string {
  let h = 0
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) | 0
  return (h >>> 0).toString(36)
}

/** The moving layer of a card: fills its parent (position: relative), lets clicks through. */
export function MotionLayer({ card }: { card: Card }) {
  const motion = card.data.motion as { code: string; loop: number; poster?: string; error?: string }
  const frame = useRef<HTMLIFrameElement>(null)
  const host = useRef<HTMLDivElement>(null)
  const [ready, setReady] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [reloads, setReloads] = useState(0)
  const zoom = useStore((s) => s.transform[2])
  const state = useRef({ visible: false, hovered: false, zoom, playing: false, loaded: false })
  state.current.zoom = zoom
  const version = `${hash(motion.code)}-${motion.loop}-${card.data.file ?? ''}-${JSON.stringify(card.data.crop ?? null)}-${reloads}`

  const post = (m: Record<string, unknown>, transfer: Transferable[] = []) =>
    frame.current?.contentWindow?.postMessage({ cxmotion: true, ...m }, '*', transfer)

  // Talk to the frame: load it when it says hello, hear errors.
  useEffect(() => {
    setReady(false)
    setError(null)
    state.current.loaded = false
    const onMessage = async (e: MessageEvent) => {
      if (e.source !== frame.current?.contentWindow || !e.data?.cxmotion) return
      const m = e.data
      if (m.type === 'hello') {
        const el = host.current
        if (!el) return
        let image: ImageBitmap | null = null
        try {
          image = await pictureFor(card)
        } catch {
          /* the picture couldn't be read: the drawing runs without it */
        }
        post(
          {
            type: 'load', code: motion.code, loop: motion.loop, palette: boardPalette(), image,
            width: el.offsetWidth || 300, height: el.offsetHeight || 225, scale: Math.min(2, window.devicePixelRatio || 1),
            at: 0.25, play: state.current.playing,
          },
          image ? [image] : [],
        )
        state.current.loaded = true
      } else if (m.type === 'ready') {
        setReady(true)
        if (motion.error) void report('')
      } else if (m.type === 'error') {
        setError(m.message)
        void report(m.message)
      } else if (m.type === 'reload') {
        setReloads((n) => n + 1)
      }
    }
    const report = (message: string) =>
      fetch(`/api/cards/${card.id}/motion/error`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CXBoards': '1' },
        body: JSON.stringify({ message }),
      }).catch(() => {})
    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
    // The frame is remounted (key) whenever the code, loop or picture changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version])

  // When to play.
  useEffect(() => {
    const layer: Layer = {
      wants: () => {
        const s = state.current
        return s.visible && s.zoom >= MIN_ZOOM && (!reduced() || s.hovered)
      },
      set: (on) => {
        if (state.current.playing === on) return
        state.current.playing = on
        if (state.current.loaded) post({ type: 'play', play: on })
      },
    }
    layers.push(layer)
    const seen = new IntersectionObserver(([entry]) => {
      state.current.visible = entry.isIntersecting
      schedule()
    })
    if (host.current) seen.observe(host.current)
    const sized = new ResizeObserver(() => {
      const el = host.current
      if (el && state.current.loaded) post({ type: 'size', width: el.offsetWidth, height: el.offsetHeight, scale: Math.min(2, window.devicePixelRatio || 1) })
    })
    if (host.current) sized.observe(host.current)
    // A theme change repaints the drawing in the new colours.
    const themed = new MutationObserver(() => state.current.loaded && post({ type: 'palette', palette: boardPalette() }))
    themed.observe(document.documentElement, { attributes: true, attributeFilter: ['style', 'data-corners', 'class'] })
    schedule()
    return () => {
      layers.splice(layers.indexOf(layer), 1)
      seen.disconnect()
      sized.disconnect()
      themed.disconnect()
      schedule()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [version])

  useEffect(() => schedule(), [zoom])

  const hover = (on: boolean) => {
    state.current.hovered = on
    schedule()
  }

  return (
    <div className="motion" ref={host} onMouseEnter={() => hover(true)} onMouseLeave={() => hover(false)}>
      {!ready && motion.poster && <img className="motion-poster" src={`/media/${motion.poster}`} alt="" draggable={false} />}
      <iframe
        key={version}
        ref={frame}
        className="motion-frame"
        src="/motion/runner"
        sandbox="allow-scripts"
        title="Animation"
        tabIndex={-1}
      />
      {error && (
        <div className="motion-error" title={error}>
          ⚠ {error}
        </div>
      )}
    </div>
  )
}
