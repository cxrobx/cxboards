// Shell: the board list, the open board, search, the trash, toasts, and the
// live connection that makes agent edits appear (and glow) as they land.

import { ReactFlowProvider } from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type Board, type BoardState, type ChangeEvent } from './api'
import { BoardCanvas, type Toast } from './Board'
import { BOOKMARKLET, ClipPage } from './Clip'
import { ContextMenu, type MenuState } from './ContextMenu'
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

function NewBoardDialog({
  templates,
  onCreate,
  onClose,
}: {
  templates: Board[]
  onCreate: (title: string, template: string | null) => void
  onClose: () => void
}) {
  const [title, setTitle] = useState('')
  const [template, setTemplate] = useState<string>('')
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form
        className="panel dialog"
        onSubmit={(e) => {
          e.preventDefault()
          if (title.trim()) onCreate(title.trim(), template || null)
        }}
      >
        <header>
          <h2>New board</h2>
        </header>
        <div className="dialog-body">
          <input
            autoFocus
            className="field"
            placeholder="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && onClose()}
          />
          <div className="template-grid">
            <button type="button" className={`template-tile${template === '' ? ' on' : ''}`} onClick={() => setTemplate('')}>
              <span className="glyph">▢</span>
              <span>Blank</span>
            </button>
            {templates.map((t) => (
              <button
                type="button"
                key={t.id}
                className={`template-tile${template === t.id ? ' on' : ''}`}
                onClick={() => {
                  setTemplate(t.id)
                  if (!title) setTitle(t.title)
                }}
              >
                <span className="glyph">▦</span>
                <span>{t.title}</span>
                <span className="muted">{t.card_count} cards</span>
              </button>
            ))}
          </div>
          {!templates.length && <p className="muted">Any board can become a template from its Board menu.</p>}
        </div>
        <footer>
          <button type="button" className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={!title.trim()}>
            Create
          </button>
        </footer>
      </form>
    </div>
  )
}

function ClipperPanel({ onClose }: { onClose: () => void }) {
  const link = useRef<HTMLAnchorElement>(null)
  useEffect(() => {
    // React refuses javascript: URLs in props, so the bookmarklet is set on the element itself.
    link.current?.setAttribute('href', BOOKMARKLET)
  }, [])
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel dialog">
        <header>
          <h2>Clip from the web</h2>
          <button className="ghost" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="dialog-body">
          <p>Drag this to your bookmarks bar:</p>
          <p>
            <a ref={link} className="bookmarklet" onClick={(e) => e.preventDefault()}>
              ✂ Clip to CXBoards
            </a>
          </p>
          <p className="muted">
            On any page, click it to save the link and any text you've selected into a board's Unsorted tray. To keep an
            image, drag it from the page straight onto a board.
          </p>
        </div>
      </div>
    </div>
  )
}

interface ToastState {
  id: number
  message: string
  action?: { label: string; run: () => void }
}

export function App() {
  if (window.location.pathname === '/clip') return <ClipPage />
  return <Shell />
}

function Shell() {
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
  const [creating, setCreating] = useState(false)
  const [clipperOpen, setClipperOpen] = useState(false)
  const [boardMenu, setBoardMenu] = useState<MenuState | null>(null)
  const [presenting, setPresenting] = useState(false)
  const [chatOpen, setChatOpen] = useState(() => {
    try {
      return localStorage.getItem('cxboards.chat-open') === '1'
    } catch {
      return false
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem('cxboards.chat-open', chatOpen ? '1' : '0')
    } catch {
      /* a convenience */
    }
  }, [chatOpen])
  const currentRef = useRef(current)
  currentRef.current = current
  const stateRef = useRef<BoardState | null>(null)
  stateRef.current = state
  const deletingHere = useRef<string | null>(null)
  const missingRef = useRef<() => void>(() => {})

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

  // The open board has gone (deleted in another window, by an agent, or a stale link): go to the
  // most recent board that's left (or the welcome screen) and say where it went.
  const boardMissing = useCallback(() => {
    const gone = currentRef.current
    const title = stateRef.current?.board.id === gone ? stateRef.current?.board.title : undefined
    // Off the local list now, so "open the most recent board" can't land on it again before the
    // refreshed list arrives (that bounced once and swapped this message for a vaguer one).
    setBoards((bs) => bs?.filter((b) => b.id !== gone && b.parent_id !== gone) ?? bs)
    setState(null)
    setCurrent(null)
    window.history.replaceState(null, '', '/')
    void loadBoards()
    showToast(title ? `“${title}” was deleted. It's in the Trash.` : "That board doesn't exist any more. It may be in the Trash.", {
      label: 'Open trash',
      run: () => setTrashOpen(true),
    })
  }, [loadBoards, showToast])
  missingRef.current = boardMissing

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
      if (e.key === '/') {
        e.preventDefault()
        setChatOpen((o) => !o)
      } else if (key === 'f' || key === 'k') {
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
      if (event.deleted) {
        if (event.board_id === currentRef.current && deletingHere.current !== event.board_id) missingRef.current()
        window.clearTimeout(listTimer)
        listTimer = window.setTimeout(() => void loadBoards(), 200)
        return
      }
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

  const newBoard = () => setCreating(true)

  const createBoard = async (title: string, template: string | null) => {
    setCreating(false)
    try {
      const board = await api.createBoard(title, undefined, template ?? undefined)
      await loadBoards()
      open(board.id)
    } catch (e) {
      showToast((e as Error).message)
    }
  }

  const present = useCallback(() => {
    setPresenting(true)
    document.documentElement.requestFullscreen?.().catch(() => {})
  }, [])

  useEffect(() => {
    if (!presenting) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPresenting(false)
    }
    const onFull = () => {
      if (!document.fullscreenElement) setPresenting(false)
    }
    window.addEventListener('keydown', onKey)
    document.addEventListener('fullscreenchange', onFull)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.removeEventListener('fullscreenchange', onFull)
      if (document.fullscreenElement) document.exitFullscreen?.().catch(() => {})
    }
  }, [presenting])

  const download = (fmt: string) => {
    if (!state) return
    const a = document.createElement('a')
    a.href = `/api/boards/${state.board.id}/export.${fmt}`
    a.download = ''
    a.click()
  }

  const openBoardMenu = (e: React.MouseEvent) => {
    if (!state) return
    const board = state.board
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect()
    setBoardMenu({
      x: r.right - 230,
      y: r.bottom + 6,
      items: [
        { label: 'Present', hint: 'P', run: present },
        {
          kind: 'sub',
          label: 'Export',
          items: [
            { label: 'Markdown (.md)', run: () => download('md') },
            { label: 'Plain text (.txt)', run: () => download('txt') },
            { label: 'Word (.docx)', run: () => download('docx') },
            { label: 'ZIP with images', run: () => download('zip') },
            { label: 'PNG image', run: () => window.dispatchEvent(new CustomEvent('cxboards:png')) },
            { label: 'PDF (print)', run: () => window.open(`/print/${board.id}/`, '_blank') },
            { kind: 'sep' },
            {
              label: 'Save to the vault',
              run: () =>
                void fetch(`/api/boards/${board.id}/export/vault`, { method: 'POST', headers: { 'X-CXBoards': '1' } })
                  .then((r) => r.json())
                  .then((r) => showToast(r.relative ? `Saved to the vault: ${r.relative}` : r.error ?? 'Couldn’t save')),
            },
          ],
        },
        {
          label: 'Duplicate board',
          run: () =>
            void api
              .duplicateBoard(board.id, { parent: board.parent_id ?? undefined })
              .then((b) => loadBoards().then(() => open(b.id)))
              .catch((e) => showToast((e as Error).message)),
        },
        board.is_template
          ? { label: 'Stop being a template', run: () => void api.updateBoard(board.id, { is_template: false }).then(loadBoards) }
          : { label: 'Make this a template', run: () => void api.updateBoard(board.id, { is_template: true }).then(loadBoards) },
        {
          label: 'Save a copy as a template',
          run: () =>
            void api
              .duplicateBoard(board.id, { template: true, title: `${board.title} template` })
              .then(() => loadBoards().then(() => showToast('Saved as a template. Pick it under New board.')))
              .catch((e) => showToast((e as Error).message)),
        },
        { kind: 'sep' },
        { label: 'Delete board', danger: true, run: () => void deleteBoard() },
      ],
    })
  }

  const deleteBoard = async () => {
    if (!state) return
    const { board } = state
    if (!window.confirm(`Move “${board.title}” and every board inside it to the trash?`)) return
    try {
      deletingHere.current = board.id  // this window is moving off it already
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
    <div className={`app${presenting ? ' presenting' : ''}`}>
      <aside className="sidebar" data-drag>
        <div className="brand" data-drag>
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
        {boards?.some((b) => b.is_template) && (
          <div className="templates">
            <div className="section-label">Templates</div>
            {boards
              .filter((b) => b.is_template)
              .map((b) => (
                <button key={b.id} className={`tree-item${b.id === current ? ' current' : ''}`} onClick={() => open(b.id)}>
                  <span className="tree-glyph">▤</span>
                  <span className="tree-title">{b.title}</span>
                </button>
              ))}
          </div>
        )}
        <div className="sidebar-foot">
          <button className="ghost" onClick={() => setTrashOpen(true)}>
            Trash
          </button>
          <button className="ghost" onClick={() => setClipperOpen(true)}>
            Clipper
          </button>
          <div className={`live${live ? ' on' : ''}`} title={live ? 'Live: agent edits appear as they happen' : 'Reconnecting…'}>
            <span className="dot" /> {live ? 'live' : 'reconnecting'}
          </div>
        </div>
      </aside>
      <main className="main">
        {current ? (
          <>
            <header className="topbar" data-drag>
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
                  <h1 data-nodrag onDoubleClick={() => setEditingTitle(true)} title="Double-click to rename">
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
                {state?.board.is_template && <span className="badge">template</span>}
                <button className={`ghost${chatOpen ? ' on' : ''}`} onClick={() => setChatOpen((o) => !o)} title="Ask about this board (⌘/)">
                  Ask
                </button>
                <button className="ghost" onClick={present} title="Present (P)">
                  Present
                </button>
                <button className="ghost board-menu" onClick={openBoardMenu}>
                  Board ▾
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
                presenting={presenting}
                chatOpen={chatOpen}
                onCloseChat={() => setChatOpen(false)}
                onPresent={present}
                onOpenBoard={(id) => open(id)}
                onState={onState}
                onMissing={boardMissing}
                onError={onError}
                onToast={showToast}
              />
            </ReactFlowProvider>
          </>
        ) : (
          <div className="welcome" data-drag>
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
      {presenting && <div className="present-hint">Click a card to look closer · click the background for all · Esc to stop</div>}
      {boardMenu && <ContextMenu state={boardMenu} onClose={() => setBoardMenu(null)} />}
      {creating && boards && (
        <NewBoardDialog templates={boards.filter((b) => b.is_template)} onCreate={(t, tpl) => void createBoard(t, tpl)} onClose={() => setCreating(false)} />
      )}
      {clipperOpen && <ClipperPanel onClose={() => setClipperOpen(false)} />}
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
