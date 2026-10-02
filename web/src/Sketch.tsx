// Drawing: a sketch card's surface, or marks over an image. Strokes are smoothed
// with perfect-freehand and stored as SVG path data, so they scale with the card
// and land in Onyx snapshots and exports as-is.
//
// Keys: D pen · E eraser · 1–4 pen size · ⌘Z undo a stroke · Esc saves.

import { getStroke } from 'perfect-freehand'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Card } from './api'

type Stroke = { d: string; color: string }

const INKS = ['#1A1A1A', '#E0A33A', '#CB4B16', '#859900', '#268BD2', '#FFFFFF']
const SIZES = [3, 6, 11, 18]

/** perfect-freehand's outline → SVG path data (M/Q/Z and plain decimals only). */
function toPath(outline: number[][]): string {
  if (!outline.length) return ''
  const f = (n: number) => n.toFixed(1)
  const parts = [`M${f(outline[0][0])},${f(outline[0][1])}`, 'Q']
  outline.forEach(([x0, y0], i) => {
    const [x1, y1] = outline[(i + 1) % outline.length]
    parts.push(`${f(x0)},${f(y0)} ${f((x0 + x1) / 2)},${f((y0 + y1) / 2)}`)
  })
  parts.push('Z')
  return parts.join(' ')
}

export function SketchEditor({ card, onClose, onError }: { card: Card; onClose: () => void; onError: (m: string) => void }) {
  const onImage = card.kind === 'image'
  const source = onImage ? card.data.annotations ?? {} : card.data
  const [natural, setNatural] = useState<[number, number] | null>(null)
  const [box, setBox] = useState<[number, number]>(source.box ?? [640, 440])
  const [strokes, setStrokes] = useState<Stroke[]>(source.paths ?? [])
  const [tool, setTool] = useState<'pen' | 'eraser'>('pen')
  const [ink, setInk] = useState(INKS[0])
  const [size, setSize] = useState(1)
  const [live, setLive] = useState<number[][] | null>(null)
  const surface = useRef<HTMLDivElement>(null)
  const saving = useRef(false)

  // On an image, the drawing surface takes the image's shape.
  useEffect(() => {
    if (!onImage || source.box) return
    const img = new Image()
    img.onload = () => {
      setNatural([img.naturalWidth, img.naturalHeight])
      const scale = Math.min(900 / img.naturalWidth, 600 / img.naturalHeight, 1.6)
      setBox([Math.round(img.naturalWidth * scale), Math.round(img.naturalHeight * scale)])
    }
    img.src = `/media/${card.data.file}`
  }, [card, onImage, source.box])

  const save = useCallback(async () => {
    if (saving.current) return
    saving.current = true
    const drawing = { paths: strokes, box }
    try {
      await api.updateCard(card.id, { data: onImage ? { annotations: drawing } : drawing })
    } catch (e) {
      onError((e as Error).message)
    }
    onClose()
  }, [box, card.id, onClose, onError, onImage, strokes])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      e.stopPropagation()
      const key = e.key.toLowerCase()
      if (e.key === 'Escape') void save()
      else if ((e.metaKey || e.ctrlKey) && key === 'z') {
        e.preventDefault()
        setStrokes((s) => s.slice(0, -1))
      } else if (key === 'd') setTool('pen')
      else if (key === 'e') setTool('eraser')
      else if (['1', '2', '3', '4'].includes(key)) setSize(Number(key) - 1)
    }
    window.addEventListener('keydown', onKey, true)
    return () => window.removeEventListener('keydown', onKey, true)
  }, [save])

  const point = (e: React.PointerEvent) => {
    const r = surface.current!.getBoundingClientRect()
    return [((e.clientX - r.left) / r.width) * box[0], ((e.clientY - r.top) / r.height) * box[1], e.pressure || 0.5]
  }

  const eraseAt = (x: number, y: number) => {
    const ctx = document.createElement('canvas').getContext('2d')!
    setStrokes((s) => s.filter((st) => !ctx.isPointInPath(new Path2D(st.d), x, y)))
  }

  const finish = (pts: number[][], pen: boolean) => {
    const outline = getStroke(pts, { size: SIZES[size], thinning: 0.55, smoothing: 0.5, streamline: 0.45, simulatePressure: !pen })
    const d = toPath(outline)
    if (d) setStrokes((s) => [...s, { d, color: ink }])
  }

  const preview = live ? toPath(getStroke(live, { size: SIZES[size], thinning: 0.55, smoothing: 0.5, streamline: 0.45, simulatePressure: true })) : ''
  const display = { width: `min(${box[0]}px, 90vw)`, aspectRatio: `${box[0]} / ${box[1]}` }

  return (
    <div className="overlay dark sketch-overlay">
      <div className="sketch-editor">
        <div className="sketch-tools">
          <button className={`chip${tool === 'pen' ? ' on' : ''}`} onClick={() => setTool('pen')} title="Pen (D)">
            ✎ pen
          </button>
          <button className={`chip${tool === 'eraser' ? ' on' : ''}`} onClick={() => setTool('eraser')} title="Eraser (E)">
            ⌫ eraser
          </button>
          <span className="sep" />
          {INKS.map((c) => (
            <button
              key={c}
              className={`swatch-dot big${ink === c ? ' picked' : ''}`}
              style={{ background: c }}
              onClick={() => {
                setInk(c)
                setTool('pen')
              }}
              title={c}
            />
          ))}
          <span className="sep" />
          {SIZES.map((s, i) => (
            <button key={s} className={`chip${size === i ? ' on' : ''}`} onClick={() => setSize(i)} title={`Size ${i + 1}`}>
              {i + 1}
            </button>
          ))}
          <span className="spacer" />
          <button className="ghost" onClick={() => setStrokes((s) => s.slice(0, -1))} disabled={!strokes.length}>
            Undo
          </button>
          <button className="ghost" onClick={() => setStrokes([])} disabled={!strokes.length}>
            Clear
          </button>
          <button className="primary" onClick={() => void save()}>
            Done
          </button>
        </div>
        <div
          ref={surface}
          className={`sketch-surface${tool === 'eraser' ? ' erasing' : ''}${onImage ? ' on-image' : ''}`}
          style={display}
          onPointerDown={(e) => {
            ;(e.target as HTMLElement).setPointerCapture(e.pointerId)
            const p = point(e)
            if (tool === 'eraser') eraseAt(p[0], p[1])
            else setLive([p])
          }}
          onPointerMove={(e) => {
            if (e.buttons !== 1) return
            const p = point(e)
            if (tool === 'eraser') eraseAt(p[0], p[1])
            else setLive((l) => (l ? [...l, p] : l))
          }}
          onPointerUp={(e) => {
            if (live) finish(live, e.pointerType === 'pen')
            setLive(null)
          }}
        >
          {onImage && <img src={`/media/${card.data.file}`} alt="" draggable={false} />}
          <svg viewBox={`0 0 ${box[0]} ${box[1]}`} preserveAspectRatio="none">
            {strokes.map((s, i) => (
              <path key={i} d={s.d} fill={s.color} />
            ))}
            {preview && <path d={preview} fill={ink} opacity={0.85} />}
          </svg>
        </div>
        <div className="sketch-hint">
          D pen · E eraser · 1–4 size · ⌘Z undo · Esc saves{natural ? ` · image ${natural[0]}×${natural[1]}` : ''}
        </div>
      </div>
    </div>
  )
}
