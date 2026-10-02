// Shell: the board list, the open board, and the live connection that makes
// agent edits appear (and glow) as they land.

import { ReactFlowProvider } from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type Board, type BoardState, type ChangeEvent } from './api'
import { BoardCanvas } from './Board'

const TOUCH_MS = 4500

function boardFromPath(): string | null {
  const match = window.location.pathname.match(/^\/b\/([^/]+)/)
  return match ? decodeURIComponent(match[1]) : null
}

function BoardTree({ boards, current, onOpen }: { boards: Board[]; current: string | null; onOpen: (id: string) => void }) {
  const kids = useMemo(() => {
    const out = new Map<string | null, Board[]>()
    for (const b of boards) out.set(b.parent_id, [...(out.get(b.parent_id) ?? []), b])
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

export function App() {
  const [boards, setBoards] = useState<Board[] | null>(null)
  const [current, setCurrent] = useState<string | null>(boardFromPath())
  const [state, setState] = useState<BoardState | null>(null)
  const [reloadKey, setReloadKey] = useState(0)
  const [touched, setTouched] = useState<Set<string>>(new Set())
  const [live, setLive] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [editingTitle, setEditingTitle] = useState(false)
  const currentRef = useRef(current)
  currentRef.current = current

  const loadBoards = useCallback(async () => {
    try {
      setBoards(await api.boards())
    } catch (e) {
      setError((e as Error).message)
    }
  }, [])

  useEffect(() => {
    void loadBoards()
  }, [loadBoards])

  const open = useCallback((id: string, replace = false) => {
    const url = `/b/${id}`
    if (replace) window.history.replaceState(null, '', url)
    else window.history.pushState(null, '', url)
    setCurrent(id)
    setState(null)
  }, [])

  // First visit with no board in the URL: open the most recently touched one.
  useEffect(() => {
    if (!current && boards?.length) {
      const top = boards.find((b) => !b.parent_id) ?? boards[0]
      open(top.id, true)
    }
  }, [boards, current, open])

  useEffect(() => {
    const onPop = () => setCurrent(boardFromPath())
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])

  // Live: one EventSource for the app. Reload the open board on its events,
  // the sidebar on any, and light up what an agent touched.
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
      }
    })
    return () => source.close()
  }, [loadBoards])

  useEffect(() => {
    if (!error) return
    const t = window.setTimeout(() => setError(null), 6000)
    return () => window.clearTimeout(t)
  }, [error])

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
      setError((e as Error).message)
    }
  }

  const deleteBoard = async () => {
    if (!state) return
    const { board } = state
    if (!window.confirm(`Delete “${board.title}” and every board inside it? This can't be undone.`)) return
    try {
      await api.deleteBoard(board.id)
      const parent = board.parent_id
      setCurrent(null)
      await loadBoards()
      if (parent) open(parent, true)
      else window.history.replaceState(null, '', '/')
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const rename = async (title: string) => {
    setEditingTitle(false)
    if (!state || !title.trim() || title === state.board.title) return
    try {
      await api.updateBoard(state.board.id, { title: title.trim() })
    } catch (e) {
      setError((e as Error).message)
    }
  }

  const onState = useCallback((s: BoardState) => setState(s), [])
  const onError = useCallback((m: string) => setError(m), [])

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
        {boards && <BoardTree boards={boards} current={current} onOpen={(id) => open(id)} />}
        <div className={`live${live ? ' on' : ''}`} title={live ? 'Live: agent edits appear as they happen' : 'Reconnecting…'}>
          <span className="dot" /> {live ? 'live' : 'reconnecting'}
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
                <button className="ghost" onClick={deleteBoard} title="Delete this board">
                  Delete board
                </button>
              </div>
            </header>
            <ReactFlowProvider key={current}>
              <BoardCanvas
                boardId={current}
                reloadKey={reloadKey}
                touched={touched}
                onOpenBoard={(id) => open(id)}
                onState={onState}
                onError={onError}
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
        {error && (
          <div className="toast" onClick={() => setError(null)}>
            {error}
          </div>
        )}
      </main>
    </div>
  )
}
