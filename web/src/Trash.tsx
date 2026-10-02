// The trash: everything deleted in the last 90 days, newest first, this
// board's things on top. Restore puts a card or board back where it was.

import { useCallback, useEffect, useState } from 'react'
import { api, type Board, type TrashItem } from './api'

function ago(iso: string): string {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000)
  if (s < 60) return 'just now'
  if (s < 3600) return `${Math.round(s / 60)} min ago`
  if (s < 86400) return `${Math.round(s / 3600)} h ago`
  return `${Math.round(s / 86400)} d ago`
}

export function TrashPanel({
  boards,
  current,
  onRestored,
  onError,
  onClose,
}: {
  boards: Board[]
  current: string | null
  onRestored: (boardId: string | null) => void
  onError: (message: string) => void
  onClose: () => void
}) {
  const [items, setItems] = useState<TrashItem[] | null>(null)
  const titles = new Map(boards.map((b) => [b.id, b.title]))

  const load = useCallback(() => {
    api.trash().then(setItems).catch((e) => onError((e as Error).message))
  }, [onError])

  useEffect(load, [load])

  const sorted = [...(items ?? [])].sort((a, b) => Number(b.board_id === current) - Number(a.board_id === current))

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel">
        <header>
          <h2>Trash</h2>
          <span className="muted">Kept for 90 days</span>
          <button className="ghost" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="panel-list">
          {items && !items.length && <p className="muted">The trash is empty.</p>}
          {sorted.map((item) => (
            <div key={item.id} className="trash-row">
              <span className="trash-kind">{item.kind}</span>
              <span className="trash-title">{item.title}</span>
              <span className="muted trash-where">
                {item.kind === 'board' ? 'a board' : titles.get(item.board_id ?? '') ?? 'a deleted board'} ·{' '}
                {ago(item.deleted_at)}
                {item.actor === 'agent' ? ' · by an agent' : ''}
              </span>
              <button
                onClick={async () => {
                  try {
                    const result = await api.restore(item.id)
                    onRestored(result.board_id)
                    load()
                  } catch (e) {
                    onError((e as Error).message)
                  }
                }}
              >
                Restore
              </button>
            </div>
          ))}
        </div>
        {!!items?.length && (
          <footer>
            <button
              className="ghost danger"
              onClick={async () => {
                if (!window.confirm(`Empty the trash? ${items.length} items go for good.`)) return
                await api.emptyTrash().catch((e) => onError((e as Error).message))
                load()
              }}
            >
              Empty trash
            </button>
          </footer>
        )}
      </div>
    </div>
  )
}
