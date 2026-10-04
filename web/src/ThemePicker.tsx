// Board ▸ Theme…: presets and custom colours. Hovering a tile (or changing a custom
// colour) previews it on the whole app; leaving or closing puts the board's own theme back.

import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Board } from './api'
import { applyPalette, type Palette } from './theme'

interface Preset {
  name: string
  label: string
  note: string
  palette: Palette | null
}

type Custom = {
  ground: string
  ink: string
  accent: string
  font: string
  corners: string
  accent2: string
  display: string
  body: string
  italic: boolean
  backdrop: string
  dim: number
  blur: number
  tint: string
  tintStrength: number
  grain: string
}

type Stored = { preset?: string; ground?: string; ink?: string; accent?: string; font?: string; corners?: string
  accent2?: string; grain?: string; fonts?: { display?: string; body?: string; display_style?: string }
  backdrop?: { file: string; dim?: number; blur?: number; tint?: string; tint_strength?: number } }

// A few Google families that suit different records; any Google Fonts family name works.
const SUGGESTED = ['Anton', 'Bebas Neue', 'Oswald', 'Playfair Display', 'Cormorant Garamond', 'Fraunces', 'Libre Baskerville',
  'DM Serif Display', 'Abril Fatface', 'Courier Prime', 'Special Elite', 'IBM Plex Mono', 'DM Sans', 'Inter', 'Work Sans', 'Karla',
  'Space Grotesk', 'Syne', 'Unbounded', 'Permanent Marker']

function toTheme(c: Custom): Record<string, unknown> {
  const out: Record<string, unknown> = { preset: 'custom', ground: c.ground, ink: c.ink, accent: c.accent, font: c.font, corners: c.corners, grain: c.grain }
  if (c.accent2) out.accent2 = c.accent2
  if (c.display.trim() || c.body.trim())
    out.fonts = { display: c.display.trim(), body: c.body.trim(), display_style: c.italic ? 'italic' : 'normal' }
  if (c.backdrop)
    out.backdrop = { file: c.backdrop, dim: c.dim, blur: c.blur, ...(c.tintStrength > 0 ? { tint: c.tint, tint_strength: c.tintStrength } : {}) }
  return out
}

const FONTS: [string, string][] = [
  ['mono', 'Mono (JetBrains)'],
  ['sans', 'Sans (Poppins)'],
  ['serif', 'Serif + Fraunces titles'],
  ['chrisx', 'Chris X (Fraunces + Poppins light)'],
]

export function ThemePicker({
  board,
  current,
  parent,
  inherited,
  images,
  onClose,
  onError,
}: {
  board: Board
  current: Palette | null
  parent: string | null // the parent board's title, when there is one
  inherited: string | null // the board this one's theme comes from, when it has none of its own
  images: { file: string; text: string }[]
  onClose: () => void
  onError: (m: string) => void
}) {
  const [presets, setPresets] = useState<Preset[]>([])
  const theme = board.theme as Stored | null
  const chosen = theme ? theme.preset ?? 'vault' : 'inherit'
  const own = theme?.preset === 'custom' ? theme : null
  const [custom, setCustom] = useState<Custom>({
    ground: own?.ground ?? current?.canvas ?? '#15171A',
    ink: own?.ink ?? current?.ink ?? '#D9D4C7',
    accent: own?.accent ?? current?.accent ?? '#E0A33A',
    font: own?.font ?? 'mono',
    corners: own?.corners ?? 'round',
    accent2: own?.accent2 ?? '',
    display: own?.fonts?.display ?? '',
    body: own?.fonts?.body ?? '',
    italic: own?.fonts?.display_style === 'italic',
    backdrop: own?.backdrop?.file ?? '',
    dim: own?.backdrop?.dim ?? 0.72,
    blur: own?.backdrop?.blur ?? 0,
    tint: own?.backdrop?.tint ?? '#000000',
    tintStrength: own?.backdrop?.tint_strength ?? 0,
    grain: own?.grain ?? 'none',
  })
  const [customOn, setCustomOn] = useState(chosen === 'custom')
  const previewTimer = useRef(0)

  const restore = useCallback(() => applyPalette(current), [current])

  useEffect(() => {
    api.themes().then(setPresets).catch((e) => onError((e as Error).message))
    const esc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        restore()
        onClose()
      }
    }
    window.addEventListener('keydown', esc, true)
    return () => window.removeEventListener('keydown', esc, true)
  }, [onClose, onError, restore])

  const save = async (value: unknown) => {
    try {
      await api.updateBoard(board.id, { theme: value })
      onClose()
    } catch (e) {
      onError((e as Error).message)
      restore()
    }
  }

  const previewCustom = (next: Custom) => {
    setCustom(next)
    setCustomOn(true)
    window.clearTimeout(previewTimer.current)
    previewTimer.current = window.setTimeout(() => {
      api
        .previewTheme(toTheme(next))
        .then((r) => applyPalette(r.palette))
        .catch(() => {})
    }, 250)
  }

  return (
    <div
      className="overlay"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) {
          restore()
          onClose()
        }
      }}
    >
      <div className="panel dialog theme-picker">
        <header>
          <h2>Theme for {board.title}</h2>
          <span className="muted">
            {inherited && !theme ? `Wearing ${inherited}'s theme. ` : ''}The whole app takes it on while this board is open, and so do the boards inside it
          </span>
        </header>
        <div className="dialog-body">
          <div className="theme-grid" onMouseLeave={restore}>
            {parent && (
              <button className={`theme-tile vault${chosen === 'inherit' ? ' on' : ''}`} onClick={() => void save(null)}>
                <div className="mini">
                  <span>↑</span>
                </div>
                <span className="name">Same as {parent}</span>
                <span className="note">Wear the parent board's theme</span>
              </button>
            )}
            {presets.map((p) => {
              const pal = p.palette
              return (
                <button
                  key={p.name}
                  className={`theme-tile${p.name === chosen ? ' on' : ''}${pal ? '' : ' vault'}`}
                  style={pal ? { background: pal.canvas, color: pal.ink, borderColor: pal.line, fontFamily: pal.font } : undefined}
                  onMouseEnter={() => applyPalette(pal)}
                  onClick={() => void save(p.name)}
                >
                  <div
                    className="mini"
                    style={pal ? { background: pal.card, border: `1px solid ${pal.line}`, borderRadius: pal.radius } : undefined}
                  >
                    <span style={pal ? { fontFamily: pal.fontDisplay } : undefined}>Aa</span>
                    <span className="dot" style={{ background: pal?.accent ?? '#E0A33A' }} />
                  </div>
                  <span className="name" style={pal ? { fontFamily: pal.fontDisplay } : undefined}>
                    {p.label}
                  </span>
                  <span className="note">{p.note}</span>
                </button>
              )
            })}
          </div>
          <h3 className="section-label">Custom{customOn ? ' (previewing)' : ''}</h3>
          <div className="custom-theme">
            {(['ground', 'ink', 'accent'] as const).map((key) => (
              <label key={key}>
                {key === 'ground' ? 'Background' : key === 'ink' ? 'Text' : 'Accent'}
                <input type="color" value={custom[key]} onChange={(e) => previewCustom({ ...custom, [key]: e.target.value })} />
              </label>
            ))}
            <label>
              Font
              <select value={custom.font} onChange={(e) => previewCustom({ ...custom, font: e.target.value })}>
                {FONTS.map(([value, name]) => (
                  <option key={value} value={value}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Corners
              <select value={custom.corners} onChange={(e) => previewCustom({ ...custom, corners: e.target.value })}>
                <option value="round">Round</option>
                <option value="square">Square</option>
              </select>
            </label>
            <label>
              Second accent
              <input type="color" value={custom.accent2 || custom.accent} onChange={(e) => previewCustom({ ...custom, accent2: e.target.value })} />
            </label>
          </div>
          <datalist id="google-fonts">
            {SUGGESTED.map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
          <div className="custom-theme">
            <label>
              Heading font
              <input className="field" list="google-fonts" placeholder="Any Google font" value={custom.display}
                onChange={(e) => setCustom({ ...custom, display: e.target.value })} onBlur={() => previewCustom(custom)} />
            </label>
            <label>
              Body font
              <input className="field" list="google-fonts" placeholder="Any Google font" value={custom.body}
                onChange={(e) => setCustom({ ...custom, body: e.target.value })} onBlur={() => previewCustom(custom)} />
            </label>
            <label className="check">
              <input type="checkbox" checked={custom.italic} onChange={(e) => previewCustom({ ...custom, italic: e.target.checked })} />
              Italic headings
            </label>
            <label>
              Grain
              <select value={custom.grain} onChange={(e) => previewCustom({ ...custom, grain: e.target.value })}>
                <option value="none">None</option>
                <option value="print">Print</option>
                <option value="film">Film</option>
              </select>
            </label>
          </div>
          <div className="custom-theme">
            <label>
              Background image
              <select value={custom.backdrop} onChange={(e) => previewCustom({ ...custom, backdrop: e.target.value })}>
                <option value="">None</option>
                {images.map((im) => (
                  <option key={im.file} value={im.file}>
                    {(im.text || im.file).slice(0, 48)}
                  </option>
                ))}
              </select>
            </label>
            {custom.backdrop && (
              <>
                <label>
                  Darken
                  <input type="range" min={0.4} max={0.95} step={0.01} value={custom.dim} onChange={(e) => previewCustom({ ...custom, dim: +e.target.value })} />
                </label>
                <label>
                  Blur
                  <input type="range" min={0} max={16} step={1} value={custom.blur} onChange={(e) => previewCustom({ ...custom, blur: +e.target.value })} />
                </label>
                <label>
                  Tint
                  <input type="color" value={custom.tint} onChange={(e) => previewCustom({ ...custom, tint: e.target.value, tintStrength: custom.tintStrength || 0.25 })} />
                </label>
                <label>
                  Tint strength
                  <input type="range" min={0} max={0.8} step={0.01} value={custom.tintStrength} onChange={(e) => previewCustom({ ...custom, tintStrength: +e.target.value })} />
                </label>
              </>
            )}
            {!images.length && <span className="muted">Add an image to this board to use it as the background.</span>}
          </div>
          <p className="muted">Colours that would be hard to read are adjusted, so text always stays legible.</p>
        </div>
        <footer>
          <button
            className="ghost"
            onClick={() => {
              restore()
              onClose()
            }}
          >
            Cancel
          </button>
          <button className="primary" disabled={!customOn} onClick={() => void save(toTheme(custom))}>
            Use these colours
          </button>
        </footer>
      </div>
    </div>
  )
}
