// A small right-click menu: items, separators, one level of submenus, and a
// colour row. Closes on Escape, on a click elsewhere, or after an item runs.

import { useEffect, useRef, useState, type ReactNode } from 'react'

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
              {open === i && (
                <div className="menu submenu">
                  <Items items={item.items} close={close} />
                </div>
              )}
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
