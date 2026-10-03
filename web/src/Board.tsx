// One board on a pannable canvas. Server state is the truth: every change is
// sent to the API and the board reloads on the change event that comes back.

import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type OnNodeDrag,
  getNodesBounds,
  getViewportForBounds,
} from '@xyflow/react'
import { toPng } from 'html-to-image'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type Board, type BoardState, type Card, type Connector, type Place } from './api'
import { ContextMenu, type MenuItem, type MenuState } from './ContextMenu'
import { ChatPanel } from './ChatPanel'
import { BoardContext, COLORS, type BoardContextValue } from './context'
import { FloatingEdge, type LineData } from './edges'
import { CardNode, ColumnNode } from './nodes'
import { CropModal, FocusEditor, LabelPicker, Lightbox } from './Overlays'
import { SketchEditor } from './Sketch'
import { Toolbar } from './Toolbar'
import { TRAY_MIME, TrayDrawer } from './Tray'

const nodeTypes = { card: CardNode, column: ColumnNode }
const edgeTypes = { floating: FloatingEdge }
const PATH_KINDS = new Set(['audio', 'video', 'file'])
const IMAGE_URL = /\.(png|jpe?g|gif|webp|svg)(\?|$)/i

/** Cards copied or cut with ⌘C / ⌘X, waiting for a paste (on this board or another). */
let clip: { ids: string[]; board: string; cut: boolean; text: string } | null = null

export type Toast = (message: string, action?: { label: string; run: () => void }) => void

function buildNodes(cards: Card[], previous: Node[], presenting: boolean): Node[] {
  const before = new Map(previous.map((n) => [n.id, n]))
  return cards
    .filter((c) => !c.column_id && !c.tray)
    .map((c) => ({
      id: c.id,
      type: c.kind === 'column' ? 'column' : 'card',
      position: { x: c.x, y: c.y },
      width: c.w,
      zIndex: c.z,
      draggable: !c.locked && !presenting,
      selected: before.get(c.id)?.selected ?? false,
      measured: before.get(c.id)?.measured, // keep sizes React Flow already measured
      data: {},
    }))
}

function buildEdges(connectors: Connector[], cards: Map<string, Card>, previous: Edge[]): Edge[] {
  const selected = new Set(previous.filter((e) => e.selected).map((e) => e.id))
  const nodeOf = (id: string) => {
    const card = cards.get(id)
    if (!card || card.tray) return null
    return card.column_id ?? card.id
  }
  return connectors.flatMap((c) => {
    const source = nodeOf(c.from_id)
    const target = nodeOf(c.to_id)
    if (!source || !target || source === target) return []
    const color = c.color || undefined
    const marker = { type: MarkerType.ArrowClosed, width: 16, height: 16, color: color ?? 'var(--line-ink)' }
    const data: LineData = { label: c.label, color: c.color, style: c.style, curve: c.curve }
    return [
      {
        id: c.id,
        source,
        target,
        type: 'floating',
        data,
        selected: selected.has(c.id),
        markerEnd: c.arrow === 'none' ? undefined : marker,
        markerStart: c.arrow === 'both' ? marker : undefined,
      },
    ]
  })
}

function cardText(card: Card): string {
  const d = card.data
  switch (card.kind) {
    case 'todo':
      return [card.text, ...(d.items ?? []).map((i: { text: string; done: boolean }) => `- [${i.done ? 'x' : ' '}] ${i.text}`)]
        .filter(Boolean)
        .join('\n')
    case 'link':
      return [d.title, d.url, card.text].filter(Boolean).join('\n')
    case 'audio':
    case 'video':
    case 'file':
      return [d.path, card.text].filter(Boolean).join('\n')
    case 'swatch':
      return d.hex
    default:
      return card.text
  }
}

interface Props {
  boardId: string
  boards: Board[]
  reloadKey: number
  touched: Set<string>
  focusId: string | null
  presenting: boolean
  chatOpen: boolean
  onCloseChat: () => void
  onPresent: () => void
  onOpenBoard: (id: string) => void
  onState: (state: BoardState) => void
  onMissing: () => void
  onError: (message: string) => void
  onToast: Toast
}

export function BoardCanvas({ boardId, boards, reloadKey, touched, focusId, presenting, chatOpen, onCloseChat, onPresent, onOpenBoard, onState, onMissing, onError, onToast }: Props) {
  const flow = useReactFlow()
  const [state, setState] = useState<BoardState | null>(null)
  const [nodes, setNodes] = useState<Node[]>([])
  const [editId, setEditId] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const [menu, setMenu] = useState<MenuState | null>(null)
  const [flash, setFlash] = useState<string | null>(null)
  const [edges, setEdges] = useState<Edge[]>([])
  const [lightbox, setLightbox] = useState<Card | null>(null)
  const [cropping, setCropping] = useState<Card | null>(null)
  const [focusing, setFocusing] = useState<Card | null>(null)
  const [picking, setPicking] = useState<{ cards: Card[]; at: { x: number; y: number } } | null>(null)
  const [trayOpen, setTrayOpen] = useState(false)
  const [sketching, setSketching] = useState<Card | null>(null)
  const wrapper = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const dragStart = useRef<{ alt: boolean; positions: Map<string, { x: number; y: number }> } | null>(null)
  const deferred = useRef<BoardState | null>(null)
  const heightTimers = useRef(new Map<string, number>())
  const nudges = useRef<{ timer: number; positions: Record<string, [number, number]> }>({ timer: 0, positions: {} })
  const fitted = useRef<string | null>(null)
  const pointer = useRef<{ x: number; y: number } | null>(null)
  const menuAt = useRef({ x: 0, y: 0 })
  const sketchRef = useRef<(card: Card) => void>((card) => setSketching(card))

  const load = useCallback(async () => {
    try {
      const next = await api.board(boardId)
      if (dragging.current) deferred.current = next
      else setState(next)
    } catch (e) {
      // The board is gone (deleted elsewhere, or a stale link): move off it rather than show an empty canvas.
      if (/^no board/.test((e as Error).message)) onMissing()
      else onError((e as Error).message)
    }
  }, [boardId, onError, onMissing])

  useEffect(() => {
    void load()
  }, [load, reloadKey])

  useEffect(() => {
    if (!state) return
    onState(state)
    setNodes((prev) => buildNodes(state.cards, prev, presenting))
    if (fitted.current !== state.board.id && !focusId) {
      fitted.current = state.board.id
      requestAnimationFrame(() => flow.fitView({ padding: 0.2, maxZoom: 1, duration: 0 }))
    }
  }, [state, onState, flow, presenting, focusId])

  const cards = useMemo(() => new Map((state?.cards ?? []).map((c) => [c.id, c])), [state])
  const childrenOf = useMemo(() => {
    const out = new Map<string, Card[]>()
    for (const c of state?.cards ?? []) {
      if (!c.column_id) continue
      out.set(c.column_id, [...(out.get(c.column_id) ?? []), c])
    }
    for (const list of out.values()) list.sort((a, b) => a.position - b.position)
    return out
  }, [state])
  const cardsRef = useRef(cards)
  cardsRef.current = cards
  const trayCards = useMemo(() => (state?.cards ?? []).filter((c) => c.tray), [state])

  useEffect(() => {
    if (state) setEdges((prev) => buildEdges(state.connectors ?? [], cards, prev))
  }, [state, cards])

  // A search result asked for this card: bring it into view and flash it.
  useEffect(() => {
    if (!focusId || !state) return
    const card = cards.get(focusId)
    if (!card) return
    fitted.current = state.board.id
    const nodeId = card.column_id ?? card.id
    requestAnimationFrame(() =>
      flow.fitView({ nodes: [{ id: nodeId }], padding: 0.6, maxZoom: 1.1, duration: 400 }),
    )
    setFlash(focusId)
    const t = window.setTimeout(() => setFlash(null), 2600)
    return () => window.clearTimeout(t)
  }, [focusId, state, cards, flow])

  const guarded = useCallback(
    async (work: () => Promise<unknown>) => {
      try {
        await work()
      } catch (e) {
        onError((e as Error).message)
        void load()
      }
    },
    [load, onError],
  )

  const selectedIds = useCallback(() => flow.getNodes().filter((n) => n.selected).map((n) => n.id), [flow])
  const selectedCards = useCallback(
    () => selectedIds().map((id) => cardsRef.current.get(id)).filter((c): c is Card => !!c),
    [selectedIds],
  )

  const undo = useCallback(
    () =>
      api
        .undo(boardId)
        .then((r) => onToast(`Undid: ${r.summary}`))
        .catch((e) => onToast((e as Error).message)),
    [boardId, onToast],
  )
  const redo = useCallback(
    () =>
      api
        .redo(boardId)
        .then((r) => onToast(`Redid: ${r.summary}`))
        .catch((e) => onToast((e as Error).message)),
    [boardId, onToast],
  )

  const deleteIds = useCallback(
    async (ids: string[]) => {
      const free = ids.filter((id) => !cardsRef.current.get(id)?.locked)
      if (free.length < ids.length) onToast('Locked cards stay put. Unlock them first.')
      if (!free.length) return
      await guarded(async () => {
        await api.deleteCards(free)
        onToast(`Moved ${free.length === 1 ? 'a card' : `${free.length} cards`} to the trash`, { label: 'Undo', run: () => void undo() })
      })
    },
    [guarded, onToast, undo],
  )

  const deleteEdges = useCallback(
    (ids: string[]) => void guarded(() => Promise.all(ids.map((id) => api.deleteConnector(id)))),
    [guarded],
  )

  const lineMenu = useCallback(
    (line: Connector): MenuItem[] => {
      const set = (patch: Partial<Connector>) => void guarded(() => api.updateConnector(line.id, patch))
      return [
        {
          label: line.label ? 'Edit label…' : 'Add a label…',
          run: () => {
            const label = window.prompt('Label', line.label)
            if (label !== null) set({ label })
          },
        },
        {
          kind: 'sub',
          label: 'Arrow',
          items: [
            { label: `${line.arrow === 'end' ? '✓ ' : ''}At the end`, run: () => set({ arrow: 'end' }) },
            { label: `${line.arrow === 'both' ? '✓ ' : ''}Both ends`, run: () => set({ arrow: 'both' }) },
            { label: `${line.arrow === 'none' ? '✓ ' : ''}None`, run: () => set({ arrow: 'none' }) },
          ],
        },
        { label: line.style === 'dashed' ? 'Solid' : 'Dashed', run: () => set({ style: line.style === 'dashed' ? 'solid' : 'dashed' }) },
        { label: line.curve ? 'Straight' : 'Curved', run: () => set({ curve: !line.curve }) },
        {
          kind: 'custom',
          render: (close) => (
            <div className="menu-colors">
              {COLORS.map((c) => (
                <button
                  key={c || 'none'}
                  className="swatch-dot big"
                  title={c || 'Default'}
                  style={{ background: c || 'transparent' }}
                  onClick={() => {
                    close()
                    set({ color: c || null })
                  }}
                />
              ))}
            </div>
          ),
        },
        { kind: 'sep' },
        { label: 'Delete line', hint: '⌫', danger: true, run: () => deleteEdges([line.id]) },
      ]
    },
    [deleteEdges, guarded],
  )

  const centre = useCallback(() => {
    const rect = wrapper.current?.getBoundingClientRect()
    const p = flow.screenToFlowPosition({
      x: (rect?.left ?? 0) + (rect?.width ?? 800) / 2,
      y: (rect?.top ?? 0) + (rect?.height ?? 600) / 3,
    })
    return { x: Math.round(p.x - 130), y: Math.round(p.y) }
  }, [flow])

  const add = useCallback(
    async (spec: Record<string, unknown>, edit = false, at?: { x: number; y: number }) => {
      try {
        // No point given (toolbar): about the middle of the view, without covering a card.
        const card = await api.addCard(boardId, { ...(at ?? { ...centre(), avoid: true }), ...spec })
        if (edit) setEditId(card.id)
      } catch (e) {
        onError((e as Error).message)
      }
    },
    [boardId, centre, onError],
  )

  const newSketch = useCallback(
    async (at?: { x: number; y: number }) => {
      try {
        const card = await api.addCard(boardId, { ...(at ?? { ...centre(), avoid: true }), kind: 'sketch', data: { paths: [], box: [640, 440] } })
        setSketching(card)
      } catch (e) {
        onError((e as Error).message)
      }
    },
    [boardId, centre, onError],
  )

  const copy = useCallback((ids: string[], cut: boolean) => {
    const text = ids.map((id) => cardText(cardsRef.current.get(id)!)).filter(Boolean).join('\n\n') || ' '
    clip = { ids, board: boardId, cut, text }
    navigator.clipboard?.writeText(text).catch(() => {
      if (clip) clip.text = ''
    })
    onToast(cut ? `Cut ${ids.length === 1 ? 'a card' : `${ids.length} cards`}. Paste to move.` : `Copied ${ids.length === 1 ? 'a card' : `${ids.length} cards`}`)
  }, [boardId, onToast])

  const pasteClip = useCallback(
    async (at?: { x: number; y: number }) => {
      if (!clip) return
      const spot = at ?? pointer.current ?? centre()
      const { ids, cut } = clip
      await guarded(async () => {
        if (cut) {
          await api.moveToBoard(ids, boardId, spot)
          clip = null
        } else {
          await api.duplicate(ids, boardId, spot)
        }
      })
    },
    [boardId, centre, guarded],
  )

  const duplicate = useCallback((ids: string[]) => void guarded(() => api.duplicate(ids)), [guarded])

  const zOrder = useCallback(
    (ids: string[], z: 'front' | 'back') => void guarded(() => Promise.all(ids.map((id) => api.updateCard(id, { z })))),
    [guarded],
  )

  const nudge = useCallback(
    (ids: string[], dx: number, dy: number) => {
      const movable = new Set(ids.filter((id) => !cardsRef.current.get(id)?.locked))
      setNodes((ns) =>
        ns.map((n) => {
          if (!movable.has(n.id)) return n
          const position = { x: n.position.x + dx, y: n.position.y + dy }
          nudges.current.positions[n.id] = [Math.round(position.x), Math.round(position.y)]
          return { ...n, position }
        }),
      )
      window.clearTimeout(nudges.current.timer)
      nudges.current.timer = window.setTimeout(() => {
        const positions = nudges.current.positions
        nudges.current.positions = {}
        if (Object.keys(positions).length) void guarded(() => api.setPositions(boardId, positions))
      }, 450) // a burst of arrow presses is one undo step
    },
    [boardId, guarded],
  )

  const ingestFiles = useCallback(
    async (files: File[], at?: Place) => {
      for (const [i, file] of files.entries()) {
        const spot: Place = at?.unsorted || at?.column ? at : { ...(at ?? centre()) }
        if (spot.x !== undefined && spot.y !== undefined) {
          spot.x += i * 24
          spot.y += i * 24
        }
        if (file.type.startsWith('image/')) {
          await guarded(() => api.uploadImage(boardId, file, spot))
          continue
        }
        try {
          const card = await api.locate(boardId, file, spot)
          if (card.matches.length > 1) onToast(`${file.name}: ${card.matches.length} identical copies on disk; using ${card.matches[0]}`)
        } catch {
          await guarded(async () => {
            await api.uploadFile(boardId, file, spot)
            onToast(`Couldn't find ${file.name} on disk, so CXBoards kept a copy.`)
          })
        }
      }
    },
    [boardId, centre, guarded, onToast],
  )

  const addAfter = useCallback(
    (card: Card) => {
      void (async () => {
        try {
          let spec: Record<string, unknown>
          if (card.column_id) {
            const siblings = childrenOf.get(card.column_id) ?? []
            spec = { kind: 'note', text: '', column: card.column_id, index: siblings.findIndex((s) => s.id === card.id) + 1 }
          } else {
            spec = { kind: 'note', text: '', near: card.id, side: 'below' }
          }
          const next = await api.addCard(boardId, spec)
          setEditId(next.id)
        } catch (e) {
          onError((e as Error).message)
        }
      })()
    },
    [boardId, childrenOf, onError],
  )

  const cardMenu = useCallback(
    (ids: string[]): MenuItem[] => {
      const list = ids.map((id) => cardsRef.current.get(id)).filter((c): c is Card => !!c)
      const one = list.length === 1 ? list[0] : null
      const canvas = list.filter((c) => !c.column_id && c.kind !== 'column')
      const allLocked = list.every((c) => c.locked)
      const items: MenuItem[] = []
      if (one && !['board', 'audio', 'video', 'file'].includes(one.kind)) items.push({ label: 'Edit', hint: '↵', run: () => setEditId(one.id) })
      if (one?.kind === 'board' && one.board) items.push({ label: 'Open board', run: () => onOpenBoard(one.board!.id) })
      if (one && PATH_KINDS.has(one.kind)) {
        items.push({ label: 'Open in its app', run: () => void guarded(() => api.openFile(one.id)) })
        items.push({ label: 'Reveal in Finder', run: () => void guarded(() => api.openFile(one.id, true)) })
      }
      if (one?.kind === 'image') {
        items.push(
          { label: 'View full size', run: () => setLightbox(one) },
          { label: 'Crop…', run: () => setCropping(one) },
          { label: 'Rotate right', run: () => void guarded(() => api.rotate(one.id, 90)) },
          { label: 'Rotate left', run: () => void guarded(() => api.rotate(one.id, -90)) },
          { label: one.data.annotations?.paths?.length ? 'Draw on it again' : 'Draw on the image', run: () => setSketching(one) },
          { label: 'Edit caption', run: () => setEditId(one.id) },
        )
      }
      if (one?.kind === 'note') {
        items.push(
          { label: 'Open full screen', run: () => setFocusing(one) },
          { label: one.data.doc ? 'Show as a note' : 'Show as a document', run: () => void guarded(() => api.updateCard(one.id, { data: { doc: !one.data.doc } })) },
        )
      }
      if (one?.kind === 'link') {
        items.push(
          { label: one.data.hide_image ? 'Show the image' : 'Hide the image', run: () => void guarded(() => api.updateCard(one.id, { data: { hide_image: !one.data.hide_image } })) },
          { label: one.data.hide_desc ? 'Show the description' : 'Hide the description', run: () => void guarded(() => api.updateCard(one.id, { data: { hide_desc: !one.data.hide_desc } })) },
        )
      }
      if (one?.kind === 'swatch') {
        items.push({
          kind: 'sub',
          label: 'Show value as',
          items: (['hex', 'rgb', 'hsl', 'none'] as const).map((f) => ({
            label: `${(one.data.format ?? 'hex') === f ? '✓ ' : ''}${f === 'none' ? 'Hidden' : f.toUpperCase()}`,
            run: () => void guarded(() => api.updateCard(one.id, { data: { format: f } })),
          })),
        })
      }
      if (one?.kind === 'board' && one.board) {
        const target = one.board.id
        items.push({ label: 'Copy link to board', run: () => void navigator.clipboard?.writeText(`${window.location.origin}/b/${target}`) })
      }
      if (items.length) items.push({ kind: 'sep' })
      items.push(
        { label: 'Duplicate', hint: '⌘D', run: () => duplicate(ids) },
        { label: 'Copy', hint: '⌘C', run: () => copy(ids, false) },
        { label: 'Cut', hint: '⌘X', run: () => copy(ids, true) },
        {
          kind: 'sub',
          label: 'Move to board',
          items: boards
            .filter((b) => b.id !== boardId && !b.is_template)
            .map((b) => ({ label: b.title, run: () => void guarded(() => api.moveToBoard(ids, b.id)) })),
        },
      )
      if (canvas.length)
        items.push({
          label: 'Group into a column…',
          run: () => {
            const title = window.prompt('Column title', '')
            if (title !== null) void guarded(() => api.group(boardId, canvas.map((c) => c.id), title))
          },
        })
      items.push({
        label: 'Make a board from these…',
        run: () => {
          const title = window.prompt('Board title', '')
          if (title) void guarded(() => api.subBoard(boardId, ids, title))
        },
      })
      if (one?.column_id) items.push({ label: 'Move out of the column', run: () => void guarded(() => api.moveCard(one.id, { column: '' })) })
      if (one?.tray) items.push({ label: 'Place on the board', run: () => void guarded(() => api.moveCard(one.id, { unsorted: false })) })
      else if (list.every((c) => c.kind !== 'column'))
        items.push({ label: 'Send to Unsorted', run: () => void guarded(() => Promise.all(ids.map((id) => api.moveCard(id, { unsorted: true })))) })
      items.push(
        { kind: 'sep' },
        {
          label: 'Labels…',
          run: () => setPicking({ cards: list, at: { x: menuAt.current.x, y: menuAt.current.y } }),
        },
        { label: 'Bring to front', hint: '⇧⌘↑', run: () => zOrder(ids, 'front') },
        { label: 'Send to back', hint: '⇧⌘↓', run: () => zOrder(ids, 'back') },
        {
          label: allLocked ? 'Unlock' : 'Lock position',
          run: () => void guarded(() => Promise.all(ids.map((id) => api.updateCard(id, { locked: !allLocked })))),
        },
        {
          kind: 'custom',
          render: (close) => (
            <div className="menu-colors">
              {COLORS.map((c) => (
                <button
                  key={c || 'none'}
                  className="swatch-dot big"
                  title={c || 'No colour'}
                  style={{ background: c || 'transparent' }}
                  onClick={() => {
                    close()
                    void guarded(() => Promise.all(ids.map((id) => api.updateCard(id, { color: c }))))
                  }}
                />
              ))}
            </div>
          ),
        },
        {
          label: list.every((c) => c.data.fill) ? 'Clear the fill' : 'Fill with its colour',
          run: () => {
            const fill = !list.every((c) => c.data.fill)
            void guarded(() =>
              Promise.all(list.map((c) => api.updateCard(c.id, { data: { fill }, ...(fill && !c.color ? { color: '#E0A33A' } : {}) }))),
            )
          },
        },
        { kind: 'sep' },
        { label: 'Delete', hint: '⌫', danger: true, disabled: allLocked, run: () => void deleteIds(ids) },
      )
      return items
    },
    [boards, boardId, copy, deleteIds, duplicate, guarded, onOpenBoard, zOrder],
  )

  const paneMenu = useCallback(
    (at: { x: number; y: number }): MenuItem[] => [
      { label: 'New note here', run: () => void add({ kind: 'note', text: '' }, true, at) },
      { label: 'New to-do here', run: () => void add({ kind: 'todo', title: '', items: [] }, true, at) },
      { label: 'New column here', run: () => void add({ kind: 'column', title: '' }, true, at) },
      { label: 'New colour swatch here', run: () => void add({ kind: 'swatch', hex: '#E0A33A' }, true, at) },
      {
        kind: 'sub',
        label: 'Add a shortcut to a board',
        items: boards
          .filter((b) => b.id !== boardId && !b.is_template)
          .map((b) => ({ label: b.title, run: () => void add({ kind: 'board', data: { board_id: b.id, shortcut: true } }, false, at) })),
      },
      { label: 'Paste here', hint: '⌘V', disabled: !clip, run: () => void pasteClip(at) },
      { kind: 'sep' },
      { label: 'Undo', hint: '⌘Z', run: () => void undo() },
      { label: 'Redo', hint: '⇧⌘Z', run: () => void redo() },
      { label: 'Select all', hint: '⌘A', run: () => setNodes((ns) => ns.map((n) => ({ ...n, selected: true }))) },
      { label: 'Fit to screen', hint: 'Z', run: () => void flow.fitView({ padding: 0.2, duration: 300 }) },
    ],
    [add, boardId, boards, flow, pasteClip, redo, undo],
  )

  const openMenu = useCallback(
    (e: { clientX: number; clientY: number; preventDefault: () => void }, items: MenuItem[]) => {
      e.preventDefault()
      menuAt.current = { x: e.clientX, y: e.clientY }
      setMenu({ x: e.clientX, y: e.clientY, items })
    },
    [],
  )

  const actions = useMemo<BoardContextValue['actions']>(
    () => ({
      update: (id, patch) => guarded(() => api.updateCard(id, patch)),
      move: (id, body) => guarded(() => api.moveCard(id, body)),
      remove: async (card) => {
        const kids = childrenOf.get(card.id)?.length ?? 0
        if (card.kind === 'column' && kids && !window.confirm(`Delete this column? Its ${kids} cards stay on the board.`)) return
        await deleteIds([card.id])
      },
      renameBoard: (id, title) => guarded(() => api.updateBoard(id, { title })),
      openBoard: onOpenBoard,
      resized: (id, width) => void guarded(() => api.updateCard(id, { w: Math.round(width) })),
      addAfter,
      openFile: (card, reveal) => void guarded(() => api.openFile(card.id, reveal)),
      menuFor: (event, card) => openMenu(event, cardMenu([card.id])),
      lightbox: (card) => setLightbox(card),
      focusEdit: (card) => setFocusing(card),
      sketch: (card) => sketchRef.current(card),
    }),
    [guarded, childrenOf, deleteIds, onOpenBoard, addAfter, openMenu, cardMenu],
  )

  // Report measured heights back, so the server's placement sees what's really on screen.
  const onNodesChange = useCallback((changes: NodeChange[]) => {
    setNodes((ns) => applyNodeChanges(changes, ns))
    for (const change of changes) {
      if (change.type !== 'dimensions' || !change.dimensions || change.resizing) continue
      const card = cardsRef.current.get(change.id)
      const height = Math.round(change.dimensions.height)
      if (!card || Math.abs(card.h - height) <= 6) continue
      window.clearTimeout(heightTimers.current.get(change.id))
      heightTimers.current.set(
        change.id,
        window.setTimeout(() => void api.updateCard(change.id, { h: height }).catch(() => {}), 400),
      )
    }
  }, [])

  /** The column or board card under a dragged node's centre (its top, for tall cards). */
  const targetUnder = useCallback(
    (node: Node): { id: string; kind: 'column' | 'board'; boardId?: string } | null => {
      const size = (id: string) => flow.getInternalNode(id)?.measured ?? {}
      const w = size(node.id).width ?? node.width ?? 0
      const h = size(node.id).height ?? 0
      const cx = node.position.x + w / 2
      const cy = node.position.y + Math.min(h / 2, 40)
      for (const n of flow.getNodes()) {
        if (n.id === node.id || n.selected) continue
        const card = cardsRef.current.get(n.id)
        if (!card) continue
        const isColumn = n.type === 'column' && node.type === 'card'
        const isBoard = card.kind === 'board' && !!card.board
        if (!isColumn && !isBoard) continue
        const nw = size(n.id).width ?? n.width ?? 0
        const nh = size(n.id).height ?? 0
        if (cx >= n.position.x && cx <= n.position.x + nw && cy >= n.position.y && cy <= n.position.y + nh)
          return isColumn ? { id: n.id, kind: 'column' } : { id: n.id, kind: 'board', boardId: card.board!.id }
      }
      return null
    },
    [flow],
  )

  const onNodeDragStart: OnNodeDrag = useCallback((event, _node, dragged) => {
    dragging.current = true
    dragStart.current = {
      alt: 'altKey' in event && event.altKey,
      positions: new Map(dragged.map((n) => [n.id, { ...n.position }])),
    }
  }, [])

  const onNodeDrag: OnNodeDrag = useCallback(
    (_event, node) => {
      if (dragStart.current?.alt) return setDropTarget(null)
      setDropTarget(targetUnder(node)?.id ?? null)
    },
    [targetUnder],
  )

  const onNodeDragStop: OnNodeDrag = useCallback(
    (event, node, dragged) => {
      dragging.current = false
      setDropTarget(null)
      const start = dragStart.current
      dragStart.current = null
      const target = start?.alt ? null : targetUnder(node)
      const ids = dragged.map((n) => n.id)
      const work = async () => {
        if (start?.alt) {
          // ⌥-drag: the originals stay, copies land where you let go.
          const left = Math.min(...dragged.map((n) => n.position.x))
          const top = Math.min(...dragged.map((n) => n.position.y))
          setNodes((ns) => ns.map((n) => (start.positions.has(n.id) ? { ...n, position: start.positions.get(n.id)! } : n)))
          await api.duplicate(ids, boardId, { x: left, y: top })
        } else if (target?.kind === 'board') {
          await api.moveToBoard(ids, target.boardId!)
          onToast(`Moved into ${cardsRef.current.get(target.id)?.board?.title ?? 'the board'}`, { label: 'Undo', run: () => void undo() })
        } else if (target?.kind === 'column' && dragged.length === 1) {
          const clientY = 'clientY' in event ? event.clientY : event.changedTouches[0]?.clientY ?? 0
          const items = Array.from(document.querySelectorAll(`[data-column="${target.id}"] [data-child]`))
          const index = items.filter((el) => {
            const r = el.getBoundingClientRect()
            return r.top + r.height / 2 < clientY
          }).length
          await api.moveCard(node.id, { column: target.id, index })
        } else {
          const positions: Record<string, [number, number]> = {}
          for (const n of dragged) positions[n.id] = [Math.round(n.position.x), Math.round(n.position.y)]
          await api.setPositions(boardId, positions)
        }
      }
      void guarded(work)
      if (deferred.current) {
        setState(deferred.current)
        deferred.current = null
      }
    },
    [boardId, guarded, onToast, targetUnder, undo],
  )

  // Keyboard: the board's shortcuts. Text fields keep their own keys.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return
      if (menu || presenting) return
      const meta = e.metaKey || e.ctrlKey
      const key = e.key.toLowerCase()
      const sel = selectedIds()
      if (meta && key === 'z') {
        e.preventDefault()
        void (e.shiftKey ? redo() : undo())
      } else if (meta && key === 'a') {
        e.preventDefault()
        setNodes((ns) => ns.map((n) => ({ ...n, selected: true })))
      } else if (meta && key === 'd' && sel.length) {
        e.preventDefault()
        duplicate(sel)
      } else if (meta && key === 'c' && sel.length) {
        e.preventDefault()
        copy(sel, false)
      } else if (meta && key === 'x' && sel.length) {
        e.preventDefault()
        copy(sel, true)
      } else if (meta && key === '0') {
        e.preventDefault()
        void flow.fitView({ padding: 0.2, duration: 300 })
      } else if (meta && (key === '=' || key === '+')) {
        e.preventDefault()
        void flow.zoomIn({ duration: 200 })
      } else if (meta && key === '-') {
        e.preventDefault()
        void flow.zoomOut({ duration: 200 })
      } else if (meta && e.shiftKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown') && sel.length) {
        e.preventDefault()
        zOrder(sel, e.key === 'ArrowUp' ? 'front' : 'back')
      } else if (!meta && (e.key === 'Delete' || e.key === 'Backspace') && (sel.length || flow.getEdges().some((x) => x.selected))) {
        e.preventDefault()
        const lines = flow.getEdges().filter((x) => x.selected).map((x) => x.id)
        if (lines.length) deleteEdges(lines)
        if (sel.length) void deleteIds(sel)
      } else if (!meta && e.key.startsWith('Arrow') && sel.length) {
        e.preventDefault()
        const step = e.shiftKey ? 48 : 8
        const dx = e.key === 'ArrowLeft' ? -step : e.key === 'ArrowRight' ? step : 0
        const dy = e.key === 'ArrowUp' ? -step : e.key === 'ArrowDown' ? step : 0
        nudge(sel, dx, dy)
      } else if (!meta && e.key === 'Escape') {
        setEditId(null)
        setNodes((ns) => ns.map((n) => (n.selected ? { ...n, selected: false } : n)))
      } else if (!meta && key === 'z' && !e.shiftKey) {
        void flow.fitView({ padding: 0.2, duration: 300 })
      } else if (!meta && e.shiftKey && key === 'd') {
        e.preventDefault()
        void newSketch(pointer.current ?? undefined)
      } else if (!meta && !e.shiftKey && key === 'p') {
        e.preventDefault()
        onPresent()
      } else if (!meta && e.key === 'Enter' && sel.length === 1) {
        const card = cardsRef.current.get(sel[0])
        if (card && !['board', 'audio', 'video', 'file'].includes(card.kind)) {
          e.preventDefault()
          setEditId(card.id)
        } else if (card?.kind === 'board' && card.board) onOpenBoard(card.board.id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [copy, deleteEdges, deleteIds, duplicate, flow, menu, newSketch, nudge, onOpenBoard, onPresent, presenting, redo, selectedIds, undo, zOrder])

  // CXBoards.app: Finder drops arrive with real paths (a browser only ever gives anonymous files).
  // A bounce is pointed at where it lives; an image is imported; a drop on a column lands in it,
  // an image dropped on a link card becomes its thumbnail.
  useEffect(() => {
    const w = window as unknown as { cxboardsNativeDrop?: (d: { paths: string[]; x: number; y: number }) => boolean }
    const handler = (drop: { paths: string[]; x: number; y: number }) => {
      if (presenting) return false
      const el = document.elementFromPoint(drop.x, drop.y) as HTMLElement | null
      const column = el?.closest('[data-column]')?.getAttribute('data-column') ?? undefined
      const nodeId = el?.closest('.react-flow__node')?.getAttribute('data-id')
      const target = nodeId ? cardsRef.current.get(nodeId) : undefined
      const p = flow.screenToFlowPosition({ x: drop.x, y: drop.y })
      void (async () => {
        for (const [i, path] of drop.paths.entries()) {
          const isImage = /\.(png|jpe?g|gif|webp|svg|heic)$/i.test(path)
          await guarded(async () => {
            if (target?.kind === 'link' && isImage && drop.paths.length === 1) {
              await api.thumbnailFromPath(target.id, path)
              return
            }
            const place = column ? { column } : { x: Math.round(p.x) + i * 24, y: Math.round(p.y) + i * 24 }
            await api.addCard(boardId, { ...(isImage ? { kind: 'image', path } : { kind: 'media', path }), ...place })
          })
        }
      })()
      return true
    }
    w.cxboardsNativeDrop = handler
    return () => {
      if (w.cxboardsNativeDrop === handler) delete w.cxboardsNativeDrop
    }
  }, [boardId, flow, guarded, presenting])

  // Board ▸ Export ▸ PNG: render the whole board (not just what's in view) to an image.
  useEffect(() => {
    const onPng = async () => {
      const viewport = document.querySelector<HTMLElement>('.react-flow__viewport')
      const nodes = flow.getNodes()
      if (!viewport || !nodes.length || !state) return
      const bounds = getNodesBounds(nodes)
      const width = Math.min(4000, Math.max(800, bounds.width + 160))
      const height = Math.min(4000, Math.max(600, bounds.height + 160))
      const vp = getViewportForBounds(bounds, width, height, 0.2, 2, 0.06)
      try {
        const url = await toPng(viewport, {
          backgroundColor: getComputedStyle(document.body).getPropertyValue('--canvas').trim() || '#fdf6e3',
          width,
          height,
          pixelRatio: 2,
          skipFonts: true,
          style: { width: `${width}px`, height: `${height}px`, transform: `translate(${vp.x}px, ${vp.y}px) scale(${vp.zoom})` },
          filter: (n) => !(n.classList?.contains('tools') || n.classList?.contains('react-flow__handle')),
        })
        const a = document.createElement('a')
        a.href = url
        a.download = `${state.board.export_slug}.png`
        a.click()
      } catch (e) {
        onError(`Couldn't make the PNG: ${(e as Error).message}`)
      }
    }
    const handler = () => void onPng()
    window.addEventListener('cxboards:png', handler)
    return () => window.removeEventListener('cxboards:png', handler)
  }, [flow, onError, state])

  // Paste: our own cards (⌘C/⌘X here or on another board), else an image, a link, a
  // file path, or text becomes a card.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const active = document.activeElement
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return
      if (presenting) return
      const text = e.clipboardData?.getData('text/plain') ?? ''
      if (clip && (text === clip.text || (!clip.text && !text))) {
        e.preventDefault()
        void pasteClip()
        return
      }
      const files = Array.from(e.clipboardData?.files ?? [])
      const at = pointer.current ?? centre()
      if (files.length) {
        e.preventDefault()
        void ingestFiles(files, at)
        return
      }
      const value = text.trim()
      if (!value) return
      e.preventDefault()
      const boardLink = value.match(/^https?:\/\/(?:127\.0\.0\.1|localhost):\d+\/b\/(b_[0-9a-f]+)/)
      if (boardLink) void add({ kind: 'board', data: { board_id: boardLink[1], shortcut: true } }, false, at)
      else if (/^https?:\/\/\S+$/.test(value) && IMAGE_URL.test(value)) void add({ kind: 'image', image_url: value }, false, at)
      else if (/^https?:\/\/\S+$/.test(value)) void add({ kind: 'link', url: value }, false, at)
      else if (/^\/\S.*\.[a-z0-9]{2,5}$/i.test(value) && !value.includes('\n')) void add({ kind: 'media', path: value }, false, at)
      else if (/^#?[0-9a-f]{6}$/i.test(value)) void add({ kind: 'swatch', hex: value }, false, at)
      else void add({ kind: 'note', text: value }, false, at)
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [add, centre, ingestFiles, pasteClip, presenting])

  const onDoubleClick = (e: React.MouseEvent) => {
    if (presenting || !(e.target as HTMLElement).classList.contains('react-flow__pane')) return
    const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY })
    void add({ kind: 'note', text: '' }, true, { x: Math.round(p.x), y: Math.round(p.y) })
  }

  const onDrop = (e: React.DragEvent) => {
    if (presenting) return
    const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY })
    const at = { x: Math.round(p.x), y: Math.round(p.y) }
    const trayCard = e.dataTransfer.getData(TRAY_MIME)
    if (trayCard) {
      e.preventDefault()
      void guarded(() => api.moveCard(trayCard, { x: at.x, y: at.y, unsorted: false }))
      return
    }
    const files = Array.from(e.dataTransfer.files)
    // An image dropped on a link card replaces its thumbnail.
    const under = (e.target as HTMLElement).closest('.react-flow__node')?.getAttribute('data-id')
    const link = under ? cardsRef.current.get(under) : undefined
    if (link?.kind === 'link' && files.length === 1 && files[0].type.startsWith('image/')) {
      e.preventDefault()
      void guarded(async () => {
        const asset = await api.uploadAsset(files[0])
        await api.updateCard(link.id, { data: { image: asset.url, hide_image: false } })
      })
      return
    }
    if (files.length) {
      e.preventDefault()
      void ingestFiles(files, at)
      return
    }
    // Dragged from a web page: an image becomes an image card, anything else a link.
    const uri = e.dataTransfer.getData('text/uri-list').split('\n').find((l) => l && !l.startsWith('#'))
    const html = e.dataTransfer.getData('text/html')
    const img = html.match(/<img[^>]+src="([^"]+)"/i)?.[1]
    if (img && /^https?:/.test(img)) {
      e.preventDefault()
      void add({ kind: 'image', image_url: img }, false, at)
    } else if (uri && /^https?:/.test(uri)) {
      e.preventDefault()
      void add(IMAGE_URL.test(uri) ? { kind: 'image', image_url: uri } : { kind: 'link', url: uri }, false, at)
    }
  }

  const context: BoardContextValue = {
    cards,
    childrenOf,
    editId,
    setEditId,
    touched,
    dropTarget,
    focusId: flash,
    presenting,
    actions,
  }

  return (
    <BoardContext.Provider value={context}>
      <div
        className={`canvas${presenting ? ' presenting' : ''}`}
        ref={wrapper}
        onDoubleClick={onDoubleClick}
        onDragOver={(e) => {
          const types = e.dataTransfer.types
          if (types.includes('Files') || types.includes('text/uri-list') || types.includes(TRAY_MIME)) e.preventDefault()
        }}
        onDrop={onDrop}
        onMouseMove={(e) => {
          const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY })
          pointer.current = { x: Math.round(p.x), y: Math.round(p.y) }
        }}
      >
        {!presenting && (
          <Toolbar
            onAdd={(spec, edit) => void add(spec, edit)}
            onImages={(files) => void ingestFiles(files)}
            extra={[{ label: 'Sketch', glyph: '✎', run: () => void newSketch() }]}
            onBoard={async (title) => {
              await guarded(async () => {
                await api.createBoard(title, boardId)
              })
            }}
          />
        )}
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={(changes: EdgeChange[]) => setEdges((es) => applyEdgeChanges(changes.filter((c) => c.type === 'select'), es))}
          onConnect={(c: Connection) => {
            if (c.source && c.target && c.source !== c.target) void guarded(() => api.connect(c.source, c.target))
          }}
          isValidConnection={(c) => c.source !== c.target}
          onEdgeContextMenu={(e, edge) => {
            if (presenting) return
            const line = state?.connectors.find((x) => x.id === edge.id)
            if (line) openMenu(e, lineMenu(line))
          }}
          onEdgeDoubleClick={(_e, edge) => {
            const line = state?.connectors.find((x) => x.id === edge.id)
            if (!line || presenting) return
            const label = window.prompt('Label', line.label)
            if (label !== null) void guarded(() => api.updateConnector(line.id, { label }))
          }}
          onNodeDragStart={onNodeDragStart}
          onNodeDrag={onNodeDrag}
          onNodeDragStop={onNodeDragStop}
          onNodeContextMenu={(e, node) => {
            if (presenting) return
            const ids = node.selected ? selectedIds() : [node.id]
            if (!node.selected) setNodes((ns) => ns.map((n) => ({ ...n, selected: n.id === node.id })))
            openMenu(e, cardMenu(ids))
          }}
          onSelectionContextMenu={(e, picked) => !presenting && openMenu(e, cardMenu(picked.map((n) => n.id)))}
          onPaneContextMenu={(e) => {
            if (presenting) return
            const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY })
            openMenu(e, paneMenu({ x: Math.round(p.x), y: Math.round(p.y) }))
          }}
          onPaneClick={() => {
            setEditId(null)
            if (presenting) void flow.fitView({ padding: 0.15, duration: 500 })
          }}
          onNodeClick={(_e, node) => {
            if (presenting) void flow.fitView({ nodes: [{ id: node.id }], padding: 0.25, maxZoom: 2, duration: 500 })
          }}
          zoomOnDoubleClick={false}
          deleteKeyCode={null}
          selectionKeyCode={null}
          multiSelectionKeyCode="Shift"
          selectionOnDrag={!presenting}
          elementsSelectable={!presenting}
          nodesDraggable={!presenting}
          panOnScroll
          panOnDrag={presenting ? true : [1, 2]}
          minZoom={0.1}
          maxZoom={2.5}
          colorMode="system"
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} size={1.2} />
          {!presenting && <Controls showInteractive={false} position="bottom-right" />}
        </ReactFlow>
        {state && !state.cards.length && (
          <div className="empty-board">
            <p>An empty board.</p>
            <p className="muted">Double-click anywhere to write, paste a link or an image, drop files from Finder, or ask an agent to lay out a plan.</p>
          </div>
        )}
        {menu && <ContextMenu state={menu} onClose={() => setMenu(null)} />}
        {!presenting && !chatOpen && (trayCards.length > 0 || trayOpen) && !trayOpen && (
          <button className="tray-button" onClick={() => setTrayOpen(true)}>
            Unsorted · {trayCards.length}
          </button>
        )}
        {chatOpen && !presenting && state && (
          <ChatPanel boardId={boardId} boardTitle={state.board.title} selection={selectedCards} onClose={onCloseChat} />
        )}
        {trayOpen && !presenting && !chatOpen && (
          <TrayDrawer
            cards={trayCards}
            onClose={() => setTrayOpen(false)}
            onPlace={(card) => void guarded(() => api.moveCard(card.id, { unsorted: false }))}
          />
        )}
        {lightbox && <Lightbox card={lightbox} onClose={() => setLightbox(null)} />}
        {cropping && <CropModal card={cropping} onClose={() => setCropping(null)} onDone={() => setCropping(null)} />}
        {focusing && <FocusEditor card={focusing} onClose={() => setFocusing(null)} />}
        {picking && <LabelPicker cards={picking.cards} at={picking.at} onClose={() => setPicking(null)} onError={onError} />}
        {sketching && <SketchEditor card={sketching} onClose={() => setSketching(null)} onError={onError} />}
      </div>
    </BoardContext.Provider>
  )
}
