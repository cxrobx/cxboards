// Shell: the board list, the open board, search, the trash, toasts, and the
// live connection that makes agent edits appear (and glow) as they land.

import { ReactFlowProvider } from '@xyflow/react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, type Board, type BoardState, type ChangeEvent } from './api'
import { BoardCanvas, type Toast } from './Board'
import { BOOKMARKLET, ClipPage } from './Clip'
import { ContextMenu, type MenuItem, type MenuState } from './ContextMenu'
import { rememberBoard, SearchPalette } from './Search'
import { BoardTree, childrenByParent, PinIcon, subtreeOf, type TreeEdit, useDock } from './Sidebar'
import { applyPalette } from './theme'
import { NewBoardDialog } from './TemplatePicker'
import { ThemePicker } from './ThemePicker'
import { TrashPanel } from './Trash'

const TOUCH_MS = 4500

function routeFromPath(): { board: string | null; card: string | null } {
  const match = window.location.pathname.match(/^\/b\/([^/]+)/)
  const card = window.location.hash.match(/^#(c_[0-9a-f]+)/)?.[1] ?? null
  return { board: match ? decodeURIComponent(match[1]) : null, card }
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
  const [creating, setCreating] = useState<false | { parent: string | null; browse?: boolean }>(false)
  const [clipperOpen, setClipperOpen] = useState(false)
  const [boardMenu, setBoardMenu] = useState<MenuState | null>(null)
  const [sideMenu, setSideMenu] = useState<MenuState | null>(null)
  const [treeEdit, setTreeEdit] = useState<TreeEdit>(null)
  const [presenting, setPresenting] = useState(false)
  const [theming, setTheming] = useState(false)
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
  const deletingHere = useRef<Set<string>>(new Set())
  const missingRef = useRef<() => void>(() => {})

  // The sidebar's dock (Sidebar.tsx): it stays out while its menu is open, a name is being typed
  // in it, or a board is being dragged in it.
  const appRef = useRef<HTMLDivElement>(null)
  const asideRef = useRef<HTMLElement>(null)
  const sideMenuRef = useRef(sideMenu)
  sideMenuRef.current = sideMenu
  const dock = useDock(appRef, asideRef, () => {
    const aside = asideRef.current
    const active = document.activeElement
    return !!sideMenuRef.current || !!aside?.querySelector('.tree-item.dragging') || (!!active && active.tagName === 'INPUT' && !!aside?.contains(active))
  })

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
        if (event.board_id === currentRef.current && !deletingHere.current.has(event.board_id)) missingRef.current()
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

  // The whole app wears the open board's theme (Vault, or no board, is the app's own look).
  useEffect(() => {
    if (!theming) applyPalette(current ? state?.palette ?? null : null)
  }, [state, current, theming])

  const newBoard = () => setCreating({ parent: null })

  const createBoard = async (title: string, template: string | null) => {
    const parent = creating ? creating.parent : null
    setCreating(false)
    try {
      const board = await api.createBoard(title, parent ?? undefined, template ?? undefined)
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
        { label: 'Theme…', run: () => setTheming(true) },
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
        { label: 'Duplicate board', run: () => duplicateBoard(board) },
        ...(board.is_template ? [] : [{ kind: 'sub' as const, label: 'Move board into', items: moveTargets(board) }]),
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
        { label: 'Delete board', danger: true, run: () => void deleteBoard(board) },
      ],
    })
  }

  const duplicateBoard = (board: Board) =>
    void api
      .duplicateBoard(board.id, { parent: board.parent_id ?? undefined })
      .then((b) => loadBoards().then(() => open(b.id)))
      .catch((e) => showToast((e as Error).message))

  // Right-click in the sidebar: on its empty space, make a folder or a board; on a board, the same
  // inside it, plus rename, duplicate, move and delete.
  const sidebarMenu = (e: React.MouseEvent) => {
    e.preventDefault()
    setSideMenu({
      x: e.clientX,
      y: e.clientY,
      items: [
        { label: 'New folder', run: () => setTreeEdit({ kind: 'folder', parent: null }) },
        { label: 'New board…', run: () => setCreating({ parent: null }) },
        { label: 'New board from template…', run: () => setCreating({ parent: null, browse: true }) },
      ],
    })
  }

  const boardRowMenu = (e: React.MouseEvent, board: Board) => {
    e.preventDefault()
    e.stopPropagation()
    const rename: MenuItem = { label: 'Rename', run: () => setTreeEdit({ kind: 'rename', id: board.id }) }
    const remove: MenuItem = { label: 'Delete', danger: true, run: () => void deleteBoard(board) }
    setSideMenu({
      x: e.clientX,
      y: e.clientY,
      items: board.is_template
        ? [
            rename,
            { label: 'Stop being a template', run: () => void api.updateBoard(board.id, { is_template: false }).then(loadBoards) },
            { kind: 'sep' },
            remove,
          ]
        : [
            { label: 'New folder inside', run: () => setTreeEdit({ kind: 'folder', parent: board.id }) },
            { label: 'New board inside…', run: () => setCreating({ parent: board.id }) },
            { label: 'New board from template inside…', run: () => setCreating({ parent: board.id, browse: true }) },
            { kind: 'sep' },
            rename,
            { label: 'Duplicate', run: () => duplicateBoard(board) },
            { kind: 'sub', label: 'Move into', items: moveTargets(board) },
            { kind: 'sep' },
            remove,
          ],
    })
  }

  // A name typed in the tree: a board's new name, or a new folder (a blank name is "New folder";
  // Esc made nothing).
  const commitTreeEdit = async (name: string) => {
    const edit = treeEdit
    setTreeEdit(null)
    const title = name.trim()
    try {
      if (edit?.kind === 'rename') {
        const board = boards?.find((b) => b.id === edit.id)
        if (!board || !title || title === board.title) return
        await api.updateBoard(board.id, { title })
        await loadBoards()
      } else if (edit?.kind === 'folder') {
        const folder = await api.createBoard(title || 'New folder', edit.parent ?? undefined, undefined, true)
        await loadBoards()
        showToast(`Made “${folder.title}”. Drag boards onto it to put them inside.`)
      }
    } catch (e) {
      showToast((e as Error).message)
    }
  }

  const moveBoard = async (id: string, parent: string | null) => {
    const title = boards?.find((b) => b.id === id)?.title ?? 'The board'
    const into = parent ? boards?.find((b) => b.id === parent)?.title ?? 'the board' : null
    try {
      await api.moveBoard(id, parent)
      await loadBoards()
      showToast(into ? `Moved “${title}” into “${into}”` : `“${title}” is a top-level board now`, {
        label: 'Undo',
        run: () =>
          void api
            .undo(id)
            .then(loadBoards)
            .catch((e) => showToast((e as Error).message)),
      })
    } catch (e) {
      showToast((e as Error).message)
    }
  }

  // "Move board into" for the Board menu: every board it can go inside, indented as in the sidebar.
  const moveTargets = (board: Board): MenuItem[] => {
    const kids = childrenByParent(boards ?? [])
    const blocked = subtreeOf(kids, board.id)
    const items: MenuItem[] = []
    const walk = (parent: string | null, depth: number) =>
      (kids.get(parent) ?? []).forEach((b) => {
        if (blocked.has(b.id)) return
        items.push({
          label: `${'   '.repeat(depth)}${depth ? '└ ' : ''}${b.title}`,
          disabled: b.id === board.parent_id,
          run: () => void moveBoard(board.id, b.id),
        })
        walk(b.id, depth + 1)
      })
    walk(null, 0)
    const top: MenuItem[] = board.parent_id
      ? [{ label: 'Top level', run: () => void moveBoard(board.id, null) }, ...(items.length ? [{ kind: 'sep' as const }] : [])]
      : []
    const all = [...top, ...items]
    return all.length ? all : [{ label: 'No other boards yet', disabled: true, run: () => {} }]
  }

  const deleteBoard = async (board: Board) => {
    const doomed = subtreeOf(childrenByParent(boards ?? []), board.id)
    const inside = doomed.size - 1
    const what = inside ? `“${board.title}” and the ${inside === 1 ? 'board' : `${inside} boards`} inside it` : `“${board.title}”`
    if (!window.confirm(`Move ${what} to the trash?`)) return
    const here = !!current && doomed.has(current)
    try {
      if (here) deletingHere.current = doomed // this window is moving off it already
      await api.deleteBoard(board.id)
      await loadBoards()
      if (here) {
        if (board.parent_id) open(board.parent_id, true)
        else {
          setCurrent(null)
          window.history.replaceState(null, '', '/')
        }
      }
      showToast(`Moved ${what} to the trash`, { label: 'Open trash', run: () => setTrashOpen(true) })
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
    <div ref={appRef} className={`app${presenting ? ' presenting' : ''}${dock.pinned ? '' : ' side-unpinned'}`}>
      <aside ref={asideRef} className="sidebar" data-drag {...dock.asideProps} onContextMenu={sidebarMenu}>
        <div className="brand" data-drag>
          <img src="/icon.png" alt="" />
          <span>CXBoards</span>
          <button
            className="side-pin"
            aria-pressed={dock.pinned}
            aria-label="Pin sidebar"
            title={`${dock.pinned ? 'Unpin' : 'Pin'} sidebar (⌘\\)`}
            onClick={() => dock.setPinned(!dock.pinned)}
          >
            <PinIcon />
          </button>
        </div>
        <button className="new-board" onClick={newBoard}>
          + New board
        </button>
        <button className="search-button" onClick={() => setSearching(true)}>
          <span>Search</span>
          <span className="hint">⌘F</span>
        </button>
        {boards && (
          <BoardTree
            boards={boards}
            current={current}
            edit={treeEdit}
            onOpen={(id) => open(id)}
            onMove={(id, parent) => void moveBoard(id, parent)}
            onMenu={boardRowMenu}
            onCommit={(name) => void commitTreeEdit(name)}
            onCancel={() => setTreeEdit(null)}
          />
        )}
        {boards?.some((b) => b.is_template) && (
          <div className="templates">
            <div className="section-label">Templates</div>
            {boards
              .filter((b) => b.is_template)
              .map((b) => (
                <button
                  key={b.id}
                  className={`tree-item${b.id === current ? ' current' : ''}`}
                  onClick={() => open(b.id)}
                  onContextMenu={(e) => boardRowMenu(e, b)}
                >
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
        <div
          className="side-grip"
          data-nodrag
          role="separator"
          aria-orientation="vertical"
          aria-label="Resize sidebar"
          title="Drag to resize · double-click to reset"
          {...dock.gripProps}
        />
      </aside>
      {!dock.pinned && !presenting && <div className="side-edge" aria-hidden="true" {...dock.edgeProps} />}
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
      {sideMenu && <ContextMenu state={sideMenu} onClose={() => setSideMenu(null)} />}
      {creating && boards && (
        <NewBoardDialog
          yours={boards.filter((b) => b.is_template)}
          inside={creating.parent ? boards.find((b) => b.id === creating.parent)?.title ?? null : null}
          browse={!!creating.browse}
          onCreate={(t, tpl) => void createBoard(t, tpl)}
          onClose={() => setCreating(false)}
        />
      )}
      {clipperOpen && <ClipperPanel onClose={() => setClipperOpen(false)} />}
      {theming && state && (
        <ThemePicker board={state.board} current={state.palette ?? null} onClose={() => setTheming(false)} onError={onError} />
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
