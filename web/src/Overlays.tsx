// Things that open over the board: the image lightbox, the crop editor, the
// full-screen writer for long notes, and the label picker.

import { useCallback, useEffect, useRef, useState } from 'react'
import Cropper, { type Area } from 'react-easy-crop'
import 'react-easy-crop/react-easy-crop.css'
import { api, type Card, type Label } from './api'
import { formatKey } from './format'
import { Markdown } from './nodes'

function useEscape(onClose: () => void) {
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
      }
    }
    window.addEventListener('keydown', esc, true)
    return () => window.removeEventListener('keydown', esc, true)
  }, [onClose])
}

export function Lightbox({ card, onClose }: { card: Card; onClose: () => void }) {
  useEscape(onClose)
  const src = `/media/${card.data.file}`
  return (
    <div className="overlay dark" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <figure className="lightbox">
        <img src={src} alt={card.text} />
        <figcaption>
          <span>{card.text}</span>
          <a href={src} download={card.text ? `${card.text}${src.slice(src.lastIndexOf('.'))}` : undefined}>
            Download
          </a>
          <a href={src} target="_blank" rel="noreferrer">
            Open in a tab
          </a>
          <button className="ghost" onClick={onClose}>
            Close
          </button>
        </figcaption>
      </figure>
    </div>
  )
}

const ASPECTS: { label: string; value: number | null }[] = [
  { label: 'Original', value: null },
  { label: '1:1', value: 1 },
  { label: '4:3', value: 4 / 3 },
  { label: '3:4', value: 3 / 4 },
  { label: '16:9', value: 16 / 9 },
  { label: '9:16', value: 9 / 16 },
]

export function CropModal({ card, onDone, onClose }: { card: Card; onDone: () => void; onClose: () => void }) {
  useEscape(onClose)
  const [natural, setNatural] = useState<number>(1)
  const [aspect, setAspect] = useState<number | null>(card.data.crop?.aspect ?? null)
  const [crop, setCrop] = useState({ x: 0, y: 0 })
  const [zoom, setZoom] = useState(1)
  const area = useRef<{ pct: Area; px: Area } | null>(null)
  const initial = card.data.crop
    ? { x: card.data.crop.x, y: card.data.crop.y, width: card.data.crop.w, height: card.data.crop.h }
    : undefined

  const save = async (reset = false) => {
    const a = area.current
    const crop = reset || !a ? null : { x: a.pct.x, y: a.pct.y, w: a.pct.width, h: a.pct.height, aspect: a.px.width / a.px.height }
    await api.updateCard(card.id, { data: { crop } })
    onDone()
  }

  return (
    <div className="overlay dark">
      <div className="crop-modal">
        <div className="crop-stage">
          <Cropper
            image={`/media/${card.data.file}`}
            crop={crop}
            zoom={zoom}
            aspect={aspect ?? natural}
            onCropChange={setCrop}
            onZoomChange={setZoom}
            onCropComplete={(pct, px) => (area.current = { pct, px })}
            onMediaLoaded={(m) => setNatural(m.naturalWidth / m.naturalHeight)}
            initialCroppedAreaPercentages={initial}
            showGrid
          />
        </div>
        <div className="crop-bar">
          {ASPECTS.map((a) => (
            <button key={a.label} className={`chip${aspect === a.value ? ' on' : ''}`} onClick={() => setAspect(a.value)}>
              {a.label}
            </button>
          ))}
          <input type="range" min={1} max={4} step={0.01} value={zoom} onChange={(e) => setZoom(Number(e.target.value))} />
          <span className="spacer" />
          <button className="ghost" onClick={() => void save(true)}>
            Remove crop
          </button>
          <button className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" onClick={() => void save()}>
            Crop
          </button>
        </div>
      </div>
    </div>
  )
}

/** Full-screen writing for long notes. Saves on close; ⌘P flips to a preview. */
export function FocusEditor({ card, onClose }: { card: Card; onClose: () => void }) {
  const [text, setText] = useState(card.text)
  const [preview, setPreview] = useState(false)
  const area = useRef<HTMLTextAreaElement>(null)
  const close = useCallback(async () => {
    if (text !== card.text) await api.updateCard(card.id, { text })
    onClose()
  }, [card, onClose, text])
  useEscape(() => void close())
  useEffect(() => area.current?.focus(), [])
  const words = text.trim() ? text.trim().split(/\s+/).length : 0
  return (
    <div className="overlay focus">
      <div className="focus-sheet">
        <div className="focus-bar">
          <span className="muted">
            {words} words · ⌘B ⌘I ⌘K ⌘J · ⌘P {preview ? 'edit' : 'preview'} · esc saves
          </span>
          <button className="ghost" onClick={() => setPreview((p) => !p)}>
            {preview ? 'Edit' : 'Preview'}
          </button>
          <button className="primary" onClick={() => void close()}>
            Done
          </button>
        </div>
        {preview ? (
          <div className="focus-preview">
            <Markdown text={text} />
          </div>
        ) : (
          <textarea
            ref={area}
            className="focus-text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'p') {
                e.preventDefault()
                setPreview(true)
                return
              }
              const next = formatKey(e)
              if (next !== null) setText(next)
            }}
          />
        )}
      </div>
    </div>
  )
}

/** Tick labels on or off for the chosen cards; type a new name to make one. */
export function LabelPicker({
  cards,
  at,
  onClose,
  onError,
}: {
  cards: Card[]
  at: { x: number; y: number }
  onClose: () => void
  onError: (m: string) => void
}) {
  const [labels, setLabels] = useState<(Label & { uses: number })[]>([])
  const [name, setName] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  useEscape(onClose)
  useEffect(() => {
    api.labels().then(setLabels).catch((e) => onError((e as Error).message))
    const away = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && onClose()
    window.addEventListener('mousedown', away, true)
    return () => window.removeEventListener('mousedown', away, true)
  }, [onClose, onError])

  const ids = cards.map((c) => c.id)
  const has = (label: Label) => cards.filter((c) => c.labels?.some((l) => l.id === label.id)).length
  const toggle = async (label: Label) => {
    const all = has(label) === cards.length
    try {
      await api.labelCards(ids, [label.name], all)
      onClose()
    } catch (e) {
      onError((e as Error).message)
    }
  }

  return (
    <div ref={ref} className="menu label-picker" style={{ left: at.x, top: at.y }}>
      <input
        autoFocus
        className="field"
        placeholder="New label…"
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={async (e) => {
          if (e.key === 'Enter' && name.trim()) {
            await api.labelCards(ids, [name.trim()]).catch((err) => onError((err as Error).message))
            onClose()
          }
        }}
      />
      {labels
        .filter((l) => !name || l.name.toLowerCase().includes(name.toLowerCase()))
        .map((l) => {
          const n = has(l)
          return (
            <button key={l.id} className="menu-item" onClick={() => void toggle(l)}>
              <span>
                <span className="label-dot" style={{ background: l.color }} /> {l.name}
              </span>
              <span className="hint">{n === cards.length ? '✓' : n ? '–' : ''}</span>
            </button>
          )
        })}
      {!labels.length && <div className="muted label-empty">No labels yet. Type one above.</div>}
    </div>
  )
}
