// ⌘F: search every board. Empty, it lists recently opened boards. Enter opens
// the highlighted result and focuses the card.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type Board, type SearchResult } from './api'

const RECENT_KEY = 'cxboards.recent'

export function rememberBoard(id: string) {
  try {
    const list: string[] = JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]')
    localStorage.setItem(RECENT_KEY, JSON.stringify([id, ...list.filter((x) => x !== id)].slice(0, 12)))
  } catch {
    /* storage unavailable: recents are a convenience */
  }
}

function recentIds(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]')
  } catch {
    return []
  }
}

const GLYPH: Record<string, string> = {
  note: '¶', todo: '☐', link: '↗', image: '▣', audio: '♪', video: '▶', file: '▤',
  column: '▥', board: '▦', swatch: '●', sketch: '✎',
}

export function SearchPalette({
  boards,
  onOpen,
  onClose,
}: {
  boards: Board[]
  onOpen: (boardId: string, cardId?: string) => void
  onClose: () => void
}) {
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [active, setActive] = useState(0)
  const input = useRef<HTMLInputElement>(null)

  useEffect(() => input.current?.focus(), [])

  useEffect(() => {
    if (!query.trim()) {
      setResults([])
      return
    }
    const t = window.setTimeout(() => {
      api.search(query).then(setResults).catch(() => setResults([]))
    }, 140)
    return () => window.clearTimeout(t)
  }, [query])

  const recent = useMemo(() => {
    const byId = new Map(boards.map((b) => [b.id, b]))
    const ids = recentIds().filter((id) => byId.has(id))
    const rest = boards.filter((b) => !ids.includes(b.id) && !b.is_template)
    return [...ids.map((id) => byId.get(id)!), ...rest].slice(0, 10)
  }, [boards])

  const rows: { key: string; glyph: string; title: string; detail: string; go: () => void }[] = query.trim()
    ? results.map((r) => ({
        key: `${r.type}-${r.card_id ?? r.board_id}`,
        glyph: r.type === 'board' ? '▦' : GLYPH[r.kind ?? 'note'] ?? '·',
        title: r.title,
        detail: r.type === 'board' ? r.snippet || 'board' : `${r.board_title}${r.snippet ? ` · ${r.snippet}` : ''}`,
        go: () => onOpen(r.board_id, r.card_id),
      }))
    : recent.map((b) => ({
        key: b.id,
        glyph: '▦',
        title: b.title,
        detail: `${b.card_count ?? 0} cards`,
        go: () => onOpen(b.id),
      }))

  useEffect(() => setActive(0), [query, results.length])

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="palette">
        <input
          ref={input}
          value={query}
          placeholder="Search every board…  (label:name to filter)"
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onClose()
            if (e.key === 'ArrowDown') {
              e.preventDefault()
              setActive((a) => Math.min(rows.length - 1, a + 1))
            }
            if (e.key === 'ArrowUp') {
              e.preventDefault()
              setActive((a) => Math.max(0, a - 1))
            }
            if (e.key === 'Enter' && rows[active]) rows[active].go()
          }}
        />
        <div className="palette-label">{query.trim() ? `${rows.length} results` : 'Recent boards'}</div>
        <div className="palette-list">
          {rows.map((row, i) => (
            <button
              key={row.key}
              className={`palette-row${i === active ? ' active' : ''}`}
              onMouseEnter={() => setActive(i)}
              onClick={row.go}
            >
              <span className="glyph">{row.glyph}</span>
              <span className="palette-title">{row.title}</span>
              <span className="palette-detail">{row.detail}</span>
            </button>
          ))}
          {query.trim() && !rows.length && <div className="muted palette-empty">Nothing matches.</div>}
        </div>
      </div>
    </div>
  )
}
