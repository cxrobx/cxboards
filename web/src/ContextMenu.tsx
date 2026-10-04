// A small right-click menu: items, separators, one level of submenus, and a
// colour row. Closes on Escape, on a click elsewhere, or after an item runs.

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'

export type MenuItem =
  | { kind?: 'item'; label: string; hint?: string; run: () => void; disabled?: boolean; danger?: boolean }
  | { kind: 'sep' }
  | { kind: 'sub'; label: string; items: MenuItem[] }
  | { kind: 'custom'; render: (close: () => void) => ReactNode }

export interface MenuState {
  x: number
  y: number
  items: MenuItem[]
}

// Opens to the right of its row; flips to the left when that would run past the
// window's edge, and slides up when it would run past the bottom.
function Submenu({ items, close }: { items: MenuItem[]; close: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [place, setPlace] = useState<{ flip: boolean; top: number } | null>(null)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    const flip = r.right > window.innerWidth - 8
    const over = r.bottom - (window.innerHeight - 8)
    setPlace({ flip, top: over > 0 ? -6 - over : -6 })
  }, [])

  return (
    <div
      ref={ref}
      className={`menu submenu${place?.flip ? ' flip' : ''}`}
      style={{ top: place?.top ?? -6, visibility: place ? undefined : 'hidden' }}
    >
      <Items items={items} close={close} />
    </div>
  )
}

function Items({ items, close }: { items: MenuItem[]; close: () => void }) {
  const [open, setOpen] = useState<number | null>(null)
  return (
    <>
      {items.map((item, i) => {
        if (item.kind === 'sep') return <div key={i} className="menu-sep" />
        if (item.kind === 'custom') return <div key={i}>{item.render(close)}</div>
        if (item.kind === 'sub')
          return (
            <div
              key={i}
              className="menu-item has-sub"
              onMouseEnter={() => setOpen(i)}
              onMouseLeave={() => setOpen((o) => (o === i ? null : o))}
            >
              <span>{item.label}</span>
              <span className="hint">▸</span>
              {open === i && <Submenu items={item.items} close={close} />}
            </div>
          )
        return (
          <button
            key={i}
            className={`menu-item${item.danger ? ' danger' : ''}`}
            disabled={item.disabled}
            onClick={() => {
              close()
              item.run()
            }}
          >
            <span>{item.label}</span>
            {item.hint && <span className="hint">{item.hint}</span>}
          </button>
        )
      })}
    </>
  )
}

export function ContextMenu({ state, onClose }: { state: MenuState; onClose: () => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [pos, setPos] = useState({ x: state.x, y: state.y })

  useEffect(() => {
    const el = ref.current
    if (el) {
      const r = el.getBoundingClientRect()
      setPos({
        x: Math.min(state.x, window.innerWidth - r.width - 8),
        y: Math.min(state.y, window.innerHeight - r.height - 8),
      })
    }
    const away = (e: MouseEvent) => {
      if (!ref.current?.contains(e.target as Node)) onClose()
    }
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('mousedown', away, true)
    window.addEventListener('keydown', esc, true)
    return () => {
      window.removeEventListener('mousedown', away, true)
      window.removeEventListener('keydown', esc, true)
    }
  }, [state, onClose])

  return (
    <div ref={ref} className="menu" style={{ left: pos.x, top: pos.y }} onContextMenu={(e) => e.preventDefault()}>
      <Items items={state.items} close={onClose} />
    </div>
  )
}
