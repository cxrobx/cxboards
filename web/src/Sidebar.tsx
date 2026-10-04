// The sidebar's board tree (folders that open and close, right-click menus, naming in place) and
// its dock, as in Onyx: pinned beside the board, or unpinned (⌘\) so it floats out from the
// window's left edge when the pointer rests there; its width is a drag of its right edge.

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type RefObject } from 'react'
import type { Board, Section } from './api'

/** Boards by parent (templates live in their own list), each list sorted by title. */
export function childrenByParent(boards: Board[]): Map<string | null, Board[]> {
  const out = new Map<string | null, Board[]>()
  for (const b of boards) {
    if (b.is_template) continue
    out.set(b.parent_id, [...(out.get(b.parent_id) ?? []), b])
  }
  for (const list of out.values()) list.sort((a, b) => a.title.localeCompare(b.title))
  return out
}

/** A board and every board nested in it: the places it can't be moved into. */
export function subtreeOf(kids: Map<string | null, Board[]>, id: string): Set<string> {
  const out = new Set([id])
  const walk = (parent: string) => (kids.get(parent) ?? []).forEach((b) => (out.add(b.id), walk(b.id)))
  walk(id)
  return out
}

function recall(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

function remember(key: string, value: string) {
  try {
    if (value) localStorage.setItem(key, value)
    else localStorage.removeItem(key)
  } catch {
    /* a convenience */
  }
}

/** A name being typed in the tree: a board's new name, a new folder's, a section's, or a new section's. */
export type TreeEdit =
  | { kind: 'rename'; id: string }
  | { kind: 'folder'; parent: string | null }
  | { kind: 'section'; id: string }
  | { kind: 'new-section'; parent: string | null; at: string | null }
  | null

const NEW_SECTION = '__new__'

/** Sections, then, for one level of the tree: what goes above each board, and what goes last. */
function placeSections(list: Board[], sections: Section[]): { above: Map<string, Section[]>; last: Section[] } {
  const rest = [...sections].sort((a, b) => (a.at === null ? 1 : b.at === null ? -1 : a.at.localeCompare(b.at)))
  const above = new Map<string, Section[]>()
  for (const b of list) {
    const here: Section[] = []
    while (rest.length && rest[0].at !== null && rest[0].at.localeCompare(b.title) <= 0) here.push(rest.shift()!)
    if (here.length) above.set(b.id, here)
  }
  return { above, last: rest }
}

/** The sidebar's own commands, from its right-click menu (App.tsx). */
export function treeCommand(kind: 'collapse' | 'reveal') {
  window.dispatchEvent(new CustomEvent('cxboards:tree', { detail: kind }))
}

const TOP = '__top__'
const SHUT_KEY = 'cxboards.shut'

export function FolderIcon({ open = false }: { open?: boolean }) {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" aria-hidden="true">
      {open ? (
        <path d="M1.75 12.75V3.75h4l1.5 1.5h5v1.5M1.75 12.75l2-5.5h10.5l-2 5.5z" />
      ) : (
        <path d="M1.75 3.75h4l1.5 1.5h7v7.5H1.75z" />
      )}
    </svg>
  )
}

/** Onyx's pin: filled while the sidebar is pinned, outlined while it floats. */
export function PinIcon() {
  return (
    <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path className="pin-head" d="M6.75 2.25v3.5L4.75 8.5h6.5l-2-2.75v-3.5z" />
      <path d="M5.75 2.25h4.5M8 8.5v5.25" />
    </svg>
  )
}

function NameField({
  depth,
  initial,
  folder,
  section = false,
  onCommit,
  onCancel,
}: {
  depth: number
  initial: string
  folder: boolean
  section?: boolean
  onCommit: (name: string) => void
  onCancel: () => void
}) {
  const done = useRef(false) // Enter, then the blur as the field goes, would commit twice
  const finish = (name: string | null) => {
    if (done.current) return
    done.current = true
    if (name === null) onCancel()
    else onCommit(name)
  }
  return (
    <div className={`tree-item editing${section ? ' tree-section' : ''}`} style={{ paddingLeft: 6 + depth * 14 }}>
      {!section && <span className="tree-chev" />}
      {!section && <span className="tree-glyph">{folder ? <FolderIcon /> : '▦'}</span>}
      <input
        className="tree-input"
        autoFocus
        defaultValue={initial}
        placeholder={section ? 'Section (blank for a line)' : folder ? 'New folder' : 'Board name'}
        spellCheck={false}
        onFocus={(e) => e.currentTarget.select()}
        onKeyDown={(e) => {
          e.stopPropagation() // the board's own keys (Delete, arrows, ⌘A) aren't for this field
          if (e.key === 'Enter') {
            e.preventDefault()
            finish(e.currentTarget.value)
          } else if (e.key === 'Escape') {
            e.preventDefault()
            finish(null)
          }
        }}
        onBlur={(e) => finish(e.currentTarget.value)}
      />
    </div>
  )
}

export function BoardTree({
  boards,
  sections,
  current,
  edit,
  onOpen,
  onMove,
  onMenu,
  onSectionMenu,
  onRenameSection,
  onPlaceSection,
  onCommit,
  onCancel,
}: {
  boards: Board[]
  sections: Section[]
  current: string | null
  edit: TreeEdit
  onOpen: (id: string) => void
  onMove: (id: string, parent: string | null) => void
  onMenu: (e: React.MouseEvent, board: Board) => void
  onSectionMenu: (e: React.MouseEvent, section: Section) => void
  onRenameSection: (id: string) => void
  onPlaceSection: (id: string, parent: string | null, at: string | null) => void
  onCommit: (name: string) => void
  onCancel: () => void
}) {
  const kids = useMemo(() => childrenByParent(boards), [boards])
  const sectionsBy = useMemo(() => {
    const out = new Map<string | null, Section[]>()
    const all = edit?.kind === 'new-section' ? [...sections, { id: NEW_SECTION, parent_id: edit.parent, at: edit.at, title: '' }] : sections
    for (const sec of all) out.set(sec.parent_id, [...(out.get(sec.parent_id) ?? []), sec])
    return out
  }, [sections, edit])
  const nav = useRef<HTMLElement>(null)

  // Folders you've closed, remembered. Opening a board opens the folders it's in, once per board,
  // so closing the folder you're in afterwards sticks.
  const [shut, setShut] = useState<Set<string>>(() => new Set((recall(SHUT_KEY) ?? '').split(',').filter(Boolean)))
  const toggle = (id: string, open?: boolean) =>
    setShut((prev) => {
      const next = new Set(prev)
      if (open ?? next.has(id)) next.delete(id)
      else next.add(id)
      remember(SHUT_KEY, [...next].join(','))
      return next
    })
  const revealed = useRef<string | null>(null)
  useEffect(() => {
    if (!current || revealed.current === current || !boards.length) return
    revealed.current = current
    const byId = new Map(boards.map((b) => [b.id, b]))
    const above: string[] = []
    for (let b = byId.get(byId.get(current)?.parent_id ?? ''); b; b = byId.get(b.parent_id ?? '')) above.push(b.id)
    if (above.some((id) => shut.has(id))) {
      setShut((prev) => {
        const next = new Set(prev)
        above.forEach((id) => next.delete(id))
        remember(SHUT_KEY, [...next].join(','))
        return next
      })
    }
  }, [current, boards, shut])

  // Right-click ▸ Collapse all closes every folder; Show current board opens the folders above the
  // open board, scrolls to it and flashes it (Onyx's reveal).
  const [flashing, setFlashing] = useState(false)
  useEffect(() => {
    const onCommand = (e: Event) => {
      const kind = (e as CustomEvent<string>).detail
      if (kind === 'collapse') {
        const next = new Set([...kids.keys()].filter((id): id is string => !!id && (kids.get(id)?.length ?? 0) > 0))
        remember(SHUT_KEY, [...next].join(','))
        setShut(next)
      } else if (kind === 'reveal' && current) {
        const byId = new Map(boards.map((b) => [b.id, b]))
        setShut((prev) => {
          const next = new Set(prev)
          for (let b = byId.get(byId.get(current)?.parent_id ?? ''); b; b = byId.get(b.parent_id ?? '')) next.delete(b.id)
          remember(SHUT_KEY, [...next].join(','))
          return next
        })
        requestAnimationFrame(() => {
          const row = nav.current?.parentElement?.querySelector<HTMLElement>('.tree-item.current')
          row?.scrollIntoView({ block: 'center', behavior: 'smooth' })
          setFlashing(true)
          window.setTimeout(() => setFlashing(false), 1200)
        })
      }
    }
    window.addEventListener('cxboards:tree', onCommand)
    return () => window.removeEventListener('cxboards:tree', onCommand)
  }, [kids, boards, current])

  // Drag a board onto another to put it inside; onto "Top level" to bring it back out.
  const [dragging, setDragging] = useState<string | null>(null)
  const [over, setOver] = useState<string | null>(null)
  const draggedParent = dragging ? boards.find((b) => b.id === dragging)?.parent_id ?? null : null
  const blocked = useMemo(() => {
    if (!dragging) return new Set<string>()
    const out = subtreeOf(kids, dragging)
    if (draggedParent) out.add(draggedParent) // already there
    return out
  }, [dragging, draggedParent, kids])
  // Drag a section onto a board (or another section) to put it just above that one.
  const [movingSection, setMovingSection] = useState<string | null>(null)
  const end = () => {
    setDragging(null)
    setMovingSection(null)
    setOver(null)
  }
  const above = (key: string, parent: string | null, at: string | null) => ({
    onDragOver: (e: React.DragEvent) => {
      if (!movingSection) return
      e.preventDefault()
      e.dataTransfer.dropEffect = 'move'
      setOver(key)
    },
    onDragLeave: (e: React.DragEvent) => {
      if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver((o) => (o === key ? null : o))
    },
    onDrop: (e: React.DragEvent) => {
      e.preventDefault()
      const moving = movingSection
      end()
      if (moving) onPlaceSection(moving, parent, at)
    },
  })
  const target = (id: string | null) => {
    const key = id ?? TOP
    return {
      onDragOver: (e: React.DragEvent) => {
        if (!dragging || (id ? blocked.has(id) : !draggedParent)) return
        e.preventDefault()
        e.dataTransfer.dropEffect = 'move'
        setOver(key)
      },
      onDragLeave: (e: React.DragEvent) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver((o) => (o === key ? null : o))
      },
      onDrop: (e: React.DragEvent) => {
        e.preventDefault()
        const moving = dragging
        end()
        if (moving) onMove(moving, id)
      },
    }
  }

  const naming = (parent: string | null) => edit?.kind === 'folder' && edit.parent === parent
  const sectionRow = (sec: Section, depth: number, at: string | null) =>
    (edit?.kind === 'section' && edit.id === sec.id) || sec.id === NEW_SECTION ? (
      <NameField key={sec.id} depth={depth} initial={sec.title} folder={false} section onCommit={onCommit} onCancel={onCancel} />
    ) : (
      <div
        key={sec.id}
        className={`tree-section${sec.title ? '' : ' line'}${over === sec.id ? ' drop-above' : ''}${movingSection === sec.id ? ' dragging' : ''}`}
        style={{ paddingLeft: 10 + depth * 14 }}
        onContextMenu={(e) => onSectionMenu(e, sec)}
        onDoubleClick={() => onRenameSection(sec.id)}
        draggable
        onDragStart={(e) => {
          e.dataTransfer.setData('application/x-cxboards-section', sec.id)
          e.dataTransfer.effectAllowed = 'move'
          requestAnimationFrame(() => setMovingSection(sec.id))
        }}
        onDragEnd={end}
        {...above(sec.id, sec.parent_id, at)}
      >
        {sec.title && <span className="tree-section-title">{sec.title}</span>}
      </div>
    )
  const render = (parent: string | null, depth: number): React.ReactNode => {
    const list = kids.get(parent) ?? []
    const placed = placeSections(list, sectionsBy.get(parent) ?? [])
    return (
    <>
      {naming(parent) && <NameField depth={depth} initial="" folder onCommit={onCommit} onCancel={onCancel} />}
      {list.map((b) => {
        const inside = (kids.get(b.id)?.length ?? 0) > 0
        const open = inside && !shut.has(b.id)
        const folder = b.is_folder || inside
        const glyph = (
          <span className="tree-glyph" style={b.swatch ? { color: b.swatch.accent } : undefined}>
            {folder ? <FolderIcon open={open} /> : '▦'}
          </span>
        )
        return (
          <div key={b.id}>
            {placed.above.get(b.id)?.map((sec) => sectionRow(sec, depth, sec.at))}
            {edit?.kind === 'rename' && edit.id === b.id ? (
              <NameField depth={depth} initial={b.title} folder={folder} onCommit={onCommit} onCancel={onCancel} />
            ) : (
              <button
                className={`tree-item${b.id === current ? ` current${flashing ? ' flash' : ''}` : ''}${over === b.id ? ' drop-into' : ''}${
                  over === `above:${b.id}` ? ' drop-above' : ''
                }${b.id === dragging ? ' dragging' : ''}`}
                style={{ paddingLeft: 6 + depth * 14 }}
                onClick={() => {
                  onOpen(b.id)
                  if (inside && !open) toggle(b.id, true)
                }}
                onContextMenu={(e) => onMenu(e, b)}
                title={b.title}
                draggable
                onDragStart={(e) => {
                  e.dataTransfer.setData('application/x-cxboards-board', b.id)
                  e.dataTransfer.effectAllowed = 'move'
                  // Next frame: changing the list inside dragstart can cancel the drag.
                  requestAnimationFrame(() => setDragging(b.id))
                }}
                onDragEnd={end}
                {...(movingSection ? above(`above:${b.id}`, b.parent_id, b.title) : target(b.id))}
              >
                <span
                  className={`tree-chev${inside ? ' has' : ''}${open ? ' open' : ''}`}
                  title={inside ? (open ? 'Close folder' : 'Open folder') : undefined}
                  onClick={(e) => {
                    if (!inside) return
                    e.stopPropagation()
                    toggle(b.id)
                  }}
                >
                  {inside && (
                    <svg viewBox="0 0 16 16" aria-hidden="true">
                      <path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  )}
                </span>
                {glyph}
                <span className="tree-title">{b.title}</span>
                <span className="tree-count">{b.card_count}</span>
              </button>
            )}
            {(open || naming(b.id)) && render(b.id, depth + 1)}
          </div>
        )
      })}
      {placed.last.map((sec) => sectionRow(sec, depth, null))}
    </>
    )
  }
  return (
    <nav className="tree" ref={nav}>
      {dragging && draggedParent && (
        <div className={`tree-top${over === TOP ? ' over' : ''}`} {...target(null)}>
          ↑ Top level
        </div>
      )}
      {render(null, 0)}
    </nav>
  )
}

const PIN_KEY = 'cxboards.sidebar'
const WIDE_KEY = 'cxboards.side-w'

/**
 * Pinned, the sidebar is the grid's first column. Unpinned, the board takes the width and the
 * sidebar waits off-screen: a beat (40 ms) on the left edge brings it out over the board, and it
 * goes a moment (400 ms) after the pointer leaves, unless it's in use (`busy`, or a resize). ⌘\
 * pins and unpins, remembered. Its width (--side-w on the app) is dragged from its right edge,
 * pinned or floating, 200 px to half the window, remembered; a double-click puts the default back.
 *
 * Out/away and the width are written straight onto the elements, not through React state, so a
 * hover or a resize doesn't re-render the board underneath.
 */
export function useDock(appRef: RefObject<HTMLElement | null>, asideRef: RefObject<HTMLElement | null>, busy: () => boolean) {
  const [pinned, setPinnedState] = useState(() => recall(PIN_KEY) !== 'unpinned')
  const pinnedRef = useRef(pinned)
  const busyRef = useRef(busy)
  busyRef.current = busy
  const over = useRef(false)
  const timer = useRef(0)
  const grip = useRef<{ x: number; w: number } | null>(null)

  const show = useCallback(
    (out: boolean) => {
      const aside = asideRef.current
      if (!aside) return
      if (out && !pinnedRef.current) aside.dataset.out = ''
      else delete aside.dataset.out
      aside.inert = !pinnedRef.current && !out // away, Tab skips it and focus can't land off-screen
    },
    [asideRef],
  )
  const later = useCallback(() => {
    window.clearTimeout(timer.current)
    if (pinnedRef.current) return
    const check = () => {
      if (pinnedRef.current || over.current) return
      if (grip.current || busyRef.current()) {
        timer.current = window.setTimeout(check, 400)
        return
      }
      show(false)
    }
    timer.current = window.setTimeout(check, 400)
  }, [show])

  const setPinned = useCallback(
    (on: boolean) => {
      pinnedRef.current = on
      setPinnedState(on)
      remember(PIN_KEY, on ? '' : 'unpinned')
      window.clearTimeout(timer.current)
      show(!on && (over.current || busyRef.current()))
      if (!on && !over.current) later()
    },
    [show, later],
  )

  const setWidth = useCallback(
    (w: number | null) => {
      const app = appRef.current
      if (!app) return
      if (w === null) {
        app.style.removeProperty('--side-w')
        remember(WIDE_KEY, '')
        return
      }
      const width = Math.round(Math.min(Math.max(w, 200), Math.max(200, window.innerWidth * 0.5)))
      app.style.setProperty('--side-w', `${width}px`)
      remember(WIDE_KEY, String(width))
    },
    [appRef],
  )

  useLayoutEffect(() => {
    const w = parseInt(recall(WIDE_KEY) ?? '', 10)
    if (w > 0) setWidth(w)
    show(false)
  }, [setWidth, show])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === '\\' && (e.metaKey || e.ctrlKey) && !e.altKey && !e.shiftKey) {
        e.preventDefault()
        setPinned(!pinnedRef.current)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      window.clearTimeout(timer.current)
    }
  }, [setPinned])

  const endGrip = () => {
    if (!grip.current) return
    grip.current = null
    document.documentElement.classList.remove('side-resizing')
    if (!pinnedRef.current && !over.current) later()
  }

  return {
    pinned,
    setPinned,
    asideProps: {
      onMouseEnter: () => {
        over.current = true
        window.clearTimeout(timer.current)
      },
      onMouseLeave: () => {
        over.current = false
        later()
      },
    },
    // 24 px deep, laid over the board while unpinned: the canvas would swallow the pointer otherwise.
    edgeProps: {
      onMouseEnter: (e: React.MouseEvent) => {
        if (e.buttons) return // dragging a card past the edge isn't asking for the sidebar
        window.clearTimeout(timer.current)
        timer.current = window.setTimeout(() => show(true), 40)
      },
      onMouseLeave: (e: React.MouseEvent) => {
        if (asideRef.current?.contains(e.relatedTarget as Node | null)) return
        window.clearTimeout(timer.current)
        if (asideRef.current?.dataset.out !== undefined) later()
      },
    },
    gripProps: {
      onPointerDown: (e: React.PointerEvent<HTMLElement>) => {
        if (e.button !== 0 || !asideRef.current) return
        e.preventDefault()
        grip.current = { x: e.clientX, w: asideRef.current.getBoundingClientRect().width }
        e.currentTarget.setPointerCapture(e.pointerId)
        document.documentElement.classList.add('side-resizing')
      },
      onPointerMove: (e: React.PointerEvent) => {
        if (grip.current) setWidth(grip.current.w + e.clientX - grip.current.x)
      },
      onPointerUp: endGrip,
      onPointerCancel: endGrip,
      onLostPointerCapture: endGrip,
      onDoubleClick: () => setWidth(null),
    },
  }
}
