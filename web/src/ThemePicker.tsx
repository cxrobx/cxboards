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

type Custom = { ground: string; ink: string; accent: string; font: string; corners: string }

const FONTS: [string, string][] = [
  ['mono', 'Mono (JetBrains)'],
  ['sans', 'Sans (Poppins)'],
  ['serif', 'Serif + Fraunces titles'],
  ['chrisx', 'Chris X (Fraunces + Poppins light)'],
]

export function ThemePicker({
  board,
  current,
  onClose,
  onError,
}: {
  board: Board
  current: Palette | null
  onClose: () => void
  onError: (m: string) => void
}) {
  const [presets, setPresets] = useState<Preset[]>([])
  const theme = board.theme as { preset?: string } & Partial<Custom> | null
  const chosen = theme?.preset ?? 'vault'
  const [custom, setCustom] = useState<Custom>({
    ground: theme?.preset === 'custom' ? theme.ground! : current?.canvas ?? '#15171A',
    ink: theme?.preset === 'custom' ? theme.ink! : current?.ink ?? '#D9D4C7',
    accent: theme?.preset === 'custom' ? theme.accent! : current?.accent ?? '#E0A33A',
    font: theme?.preset === 'custom' ? theme.font! : 'mono',
    corners: theme?.preset === 'custom' ? theme.corners! : 'round',
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
        .previewTheme({ preset: 'custom', ...next })
        .then((r) => applyPalette(r.palette))
        .catch(() => {})
    }, 120)
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
          <span className="muted">The whole app takes it on while this board is open</span>
        </header>
        <div className="dialog-body">
          <div className="theme-grid" onMouseLeave={restore}>
            {presets.map((p) => {
              const pal = p.palette
              return (
                <button
                  key={p.name}
                  className={`theme-tile${p.name === chosen ? ' on' : ''}${pal ? '' : ' vault'}`}
                  style={pal ? { background: pal.canvas, color: pal.ink, borderColor: pal.line, fontFamily: pal.font } : undefined}
                  onMouseEnter={() => applyPalette(pal)}
                  onClick={() => void save(p.name === 'vault' ? null : p.name)}
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
          <button className="primary" disabled={!customOn} onClick={() => void save({ preset: 'custom', ...custom })}>
            Use these colours
          </button>
        </footer>
      </div>
    </div>
  )
}
