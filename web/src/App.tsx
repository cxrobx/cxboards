// Shell: the board list, the open board, search, the trash, toasts, and the
// live connection that makes agent edits appear (and glow) as they land.

import { ReactFlowProvider } from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type Board, type BoardState, type ChangeEvent } from './api'
import { BoardCanvas, type Toast } from './Board'
import { rememberBoard, SearchPalette } from './Search'
import { TrashPanel } from './Trash'

const TOUCH_MS = 4500

function routeFromPath(): { board: string | null; card: string | null } {
  const match = window.location.pathname.match(/^\/b\/([^/]+)/)
  const card = window.location.hash.match(/^#(c_[0-9a-f]+)/)?.[1] ?? null
  return { board: match ? decodeURIComponent(match[1]) : null, card }
}

function BoardTree({ boards, current, onOpen }: { boards: Board[]; current: string | null; onOpen: (id: string) => void }) {
  const kids = useMemo(() => {
    const out = new Map<string | null, Board[]>()
    for (const b of boards) {
      if (b.is_template) continue
      out.set(b.parent_id, [...(out.get(b.parent_id) ?? []), b])
    }
    for (const list of out.values()) list.sort((a, b) => a.title.localeCompare(b.title))
    return out
  }, [boards])
  const render = (parent: string | null, depth: number): React.ReactNode =>
    (kids.get(parent) ?? []).map((b) => (
      <div key={b.id}>
        <button
          className={`tree-item${b.id === current ? ' current' : ''}`}
          style={{ paddingLeft: 12 + depth * 14 }}
          onClick={() => onOpen(b.id)}
          title={b.title}
        >
          <span className="tree-glyph">{depth ? '└' : '▦'}</span>
          <span className="tree-title">{b.title}</span>
          <span className="tree-count">{b.card_count}</span>
        </button>
        {render(b.id, depth + 1)}
      </div>
    ))
  return <nav className="tree">{render(null, 0)}</nav>
}

interface ToastState {
  id: number
  message: string
  action?: { label: string; run: () => void }
}

export function App() {
  const initial = routeFromPath()
  const [boards, setBoards] = useState<Board[] | null>(null)
  const [current, setCurrent] = useState<string | null>(initial.board)
  const [focusId, setFocusId] = useState<string | null>(initial.card)
  const [state, setState] = useState<BoardState | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [live, setLive] = useState(false)
  const [toast, setToast] = useState<ToastState | null>(null)
  const [editingTitle, setEditingTitle] = useState(false)
  const [searching, setSearching] = useState(false)
  const [trashOpen, setTrashOpen] = useState(false)
  const currentRef = useRef(current)
  currentRef.current = current

  const showToast: Toast = useCallback((message, action) => {
    setToast({ id: Date.now() + Math.random(), message, action })
  }, [])

  useEffect(() => {
    if (!toast) return
    const t = window.setTimeout(() => setToast(null), toast.action ? 8000 : 4500)
    return () => window.clearTimeout(t)
  }, [toast])

  const loadBoards = useCallback(async () => {
    try {
      setBoards(await api.boards())
    } catch (e) {
      showToast((e as Error).message)
    }
  }, [showToast])

  useEffect(() => {
    void loadBoards()
  }, [loadBoards])

  const open = useCallback((id: string, replace = false, card: string | null = null) => {
    const url = `/b/${id}${card ? `#${card}` : ''}`
    if (replace) window.history.replaceState(null, '', url)
    else window.history.pushState(null, '', url)
    rememberBoard(id)
    setFocusId(card)
    if (id !== currentRef.current) {
      setCurrent(id)
      setState(null)
    }
  }, [])

  // First visit with no board in the URL: open the most recently touched one.
  useEffect(() => {
    if (!current && boards?.length) {
      const top = boards.find((b) => !b.parent_id && !b.is_template) ?? boards[0]
      open(top.id, true)
    }
    if (current) rememberBoard(current)
  }, [boards, current, open])

  useEffect(() => {
    const onPop = () => {
      const route = routeFromPath()
      setCurrent(route.board)
      setFocusId(route.card)
    }
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // App-wide keys: ⌘F search, ⌘[ / ⌘] back and forward, ⌘U up to the parent board.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey
      if (!meta) return
      const key = e.key.toLowerCase()
      if (key === 'f' || key === 'k') {
        e.preventDefault()
        setSearching(true)
      } else if (e.key === '[') {
        e.preventDefault()
        window.history.back()
      } else if (e.key === ']') {
        e.preventDefault()
        window.history.forward()
      } else if (key === 'u' && state?.board.parent_id) {
        e.preventDefault()
        open(state.board.parent_id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, state])

  // Live: one EventSource for the app. Reload the open board on its events,
  // the sidebar on any, light up what an agent touched, and offer to undo it.
  useEffect(() => {
    let listTimer = 0
    const source = new EventSource('/api/events')
    source.onopen = () => setLive(true)
    source.onerror = () => setLive(false)
    source.addEventListener('change', (msg) => {
      const event = JSON.parse((msg as MessageEvent).data) as ChangeEvent
      if (event.board_id === currentRef.current) setReloadKey((k) => k + 1)
      window.clearTimeout(listTimer)
      listTimer = window.setTimeout(() => void loadBoards(), 400)
      if (event.actor === 'agent' && event.card_ids.length) {
        setTouched((prev) => new Set([...prev, ...event.card_ids]))
        window.setTimeout(() => {
          setTouched((prev) => {
            const next = new Set(prev)
            event.card_ids.forEach((id) => next.delete(id))
            return next
          })
        }, TOUCH_MS)
        if (event.history_id && event.board_id === currentRef.current) {
          const historyId = event.history_id
          showToast(`An agent ${event.summary ?? 'changed the board'}`, {
            label: 'Undo',
            run: () =>
              void api
                .undoStep(historyId)
                .then(() => showToast("Undid the agent's change"))
                .catch((e) => showToast((e as Error).message)),
          })
        }
      }
    })
    return () => source.close()
  }, [loadBoards, showToast])

  useEffect(() => {
    document.title = state ? `${state.board.title} · CXBoards` : 'CXBoards'
  }, [state])

  const newBoard = async () => {
    const title = window.prompt('New board title')
    if (!title?.trim()) return
    try {
      const board = await api.createBoard(title.trim())
      await loadBoards()
      open(board.id)
    } catch (e) {
      showToast((e as Error).message)
    }
  }

  const deleteBoard = async () => {
    if (!state) return
    const { board } = state
    if (!window.confirm(`Move “${board.title}” and every board inside it to the trash?`)) return
    try {
      await api.deleteBoard(board.id)
      const parent = board.parent_id
      await loadBoards()
      if (parent) open(parent, true)
      else {
        setCurrent(null)
        window.history.replaceState(null, '', '/')
      }
      showToast(`Moved “${board.title}” to the trash`, { label: 'Open trash', run: () => setTrashOpen(true) })
    } catch (e) {
      showToast((e as Error).message)
    }
  }

  const rename = async (title: string) => {
    setEditingTitle(false)
    if (!state || !title.trim() || title === state.board.title) return
    try {
      await api.updateBoard(state.board.id, { title: title.trim() })
    } catch (e) {
      showToast((e as Error).message)
    }
  }

  const onState = useCallback((s: BoardState) => setState(s), [])
  const onError = useCallback((m: string) => showToast(m), [showToast])

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <img src="/icon.png" alt="" />
          <span>CXBoards</span>
        </div>
        <button className="new-board" onClick={newBoard}>
          + New board
        </button>
        <button className="search-button" onClick={() => setSearching(true)}>
          <span>Search</span>
          <span className="hint">⌘F</span>
        </button>
        {boards && <BoardTree boards={boards} current={current} onOpen={(id) => open(id)} />}
        <div className="sidebar-foot">
          <button className="ghost" onClick={() => setTrashOpen(true)}>
            Trash
          </button>
          <div className={`live${live ? ' on' : ''}`} title={live ? 'Live: agent edits appear as they happen' : 'Reconnecting…'}>
            <span className="dot" /> {live ? 'live' : 'reconnecting'}
          </div>
        </div>
      </aside>
      <main className="main">
        {current ? (
          <>
            <header className="topbar">
              <div className="crumbs">
                {state?.breadcrumbs.slice(0, -1).map((b) => (
                  <span key={b.id}>
                    <a
                      href={`/b/${b.id}`}
                      onClick={(e) => {
                        e.preventDefault()
                        open(b.id)
                      }}
                    >
                      {b.title}
                    </a>
                    <span className="sep">/</span>
                  </span>
                ))}
                {editingTitle && state ? (
                  <input
                    className="title-input"
                    autoFocus
                    defaultValue={state.board.title}
                    onBlur={(e) => void rename(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') void rename((e.target as HTMLInputElement).value)
                      if (e.key === 'Escape') setEditingTitle(false)
                    }}
                  />
                ) : (
                  <h1 onDoubleClick={() => setEditingTitle(true)} title="Double-click to rename">
                    {state?.board.title ?? ''}
                  </h1>
                )}
              </div>
              <div className="topbar-right">
                {state && (
                  <span className="snapshot" title="A static copy of this board is kept in Onyx">
                    Onyx: Muzik/Boards/{state.board.export_slug}
                  </span>
                )}
                <button className="ghost" onClick={deleteBoard} title="Move this board to the trash">
                  Delete board
                </button>
              </div>
            </header>
            <ReactFlowProvider key={current}>
              <BoardCanvas
                boardId={current}
                boards={boards ?? []}
                reloadKey={reloadKey}
                touched={touched}
                focusId={focusId}
                presenting={false}
                onOpenBoard={(id) => open(id)}
                onState={onState}
                onError={onError}
                onToast={showToast}
              />
            </ReactFlowProvider>
          </>
        ) : (
          <div className="welcome">
            <img src="/icon.png" alt="" />
            <h1>CXBoards</h1>
            <p className="muted">Plan sessions on a board you and your agents share.</p>
            <button className="new-board" onClick={newBoard}>
              + New board
            </button>
          </div>
        )}
        {toast && (
          <div className="toast" key={toast.id}>
            <span>{toast.message}</span>
            {toast.action && (
              <button
                onClick={() => {
                  toast.action!.run()
                  setToast(null)
                }}
              >
                {toast.action.label}
              </button>
            )}
            <button className="toast-close" onClick={() => setToast(null)} title="Dismiss">
              ×
            </button>
          </div>
        )}
      </main>
      {searching && (
        <SearchPalette
          boards={boards ?? []}
          onClose={() => setSearching(false)}
          onOpen={(boardId, cardId) => {
            setSearching(false)
            open(boardId, false, cardId ?? null)
          }}
        />
      )}
      {trashOpen && (
        <TrashPanel
          boards={boards ?? []}
          current={current}
          onClose={() => setTrashOpen(false)}
          onError={onError}
          onRestored={(boardId) => {
            void loadBoards()
            showToast('Restored', boardId && boardId !== current ? { label: 'Go there', run: () => open(boardId) } : undefined)
          }}
        />
      )}
    </div>
  )
}
