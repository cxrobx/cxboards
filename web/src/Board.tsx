// One board on a pannable canvas. Server state is the truth: every change is
// sent to the API and the board reloads on the change event that comes back.

import {
  Background,
  Controls,
  ReactFlow,
  applyNodeChanges,
  useReactFlow,
  type Node,
  type NodeChange,
  type OnNodeDrag,
} from '@xyflow/react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, type BoardState, type Card } from './api'
import { BoardContext, type BoardContextValue } from './context'
import { CardNode, ColumnNode } from './nodes'
import { Toolbar } from './Toolbar'

const nodeTypes = { card: CardNode, column: ColumnNode }

function buildNodes(cards: Card[], previous: Node[]): Node[] {
  const before = new Map(previous.map((n) => [n.id, n]))
  return cards
    .filter((c) => !c.column_id)
    .map((c) => ({
      id: c.id,
      type: c.kind === 'column' ? 'column' : 'card',
      position: { x: c.x, y: c.y },
      width: c.w,
      zIndex: c.z,
      selected: before.get(c.id)?.selected ?? false,
      measured: before.get(c.id)?.measured, // keep sizes React Flow already measured
      data: {},
    }))
}

interface Props {
  boardId: string
  reloadKey: number
  touched: Set<string>
  onOpenBoard: (id: string) => void
  onState: (state: BoardState) => void
  onError: (message: string) => void
}

export function BoardCanvas({ boardId, reloadKey, touched, onOpenBoard, onState, onError }: Props) {
  const flow = useReactFlow()
  const [state, setState] = useState<BoardState | null>(null)
  const [nodes, setNodes] = useState<Node[]>([])
  const [editId, setEditId] = useState<string | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)
  const wrapper = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const deferred = useRef<BoardState | null>(null)
  const heightTimers = useRef(new Map<string, number>())
  const fitted = useRef<string | null>(null)

  const load = useCallback(async () => {
    try {
      const next = await api.board(boardId)
      if (dragging.current) deferred.current = next
      else setState(next)
    } catch (e) {
      onError((e as Error).message)
    }
  }, [boardId, onError])

  useEffect(() => {
    void load()
  }, [load, reloadKey])

  useEffect(() => {
    if (!state) return
    onState(state)
    setNodes((prev) => buildNodes(state.cards, prev))
    if (fitted.current !== state.board.id) {
      fitted.current = state.board.id
      requestAnimationFrame(() => flow.fitView({ padding: 0.2, maxZoom: 1, duration: 0 }))
    }
  }, [state, onState, flow])

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

  const actions = useMemo<BoardContextValue['actions']>(
    () => ({
      update: (id, patch) => guarded(() => api.updateCard(id, patch)),
      move: (id, body) => guarded(() => api.moveCard(id, body)),
      remove: async (card) => {
        const kids = childrenOf.get(card.id)?.length ?? 0
        if (card.kind === 'column' && kids && !window.confirm(`Delete this column? Its ${kids} cards stay on the board.`)) return
        if (card.kind === 'board' && !window.confirm('Remove this board card? The board itself is kept as a top-level board.')) return
        await guarded(() => api.deleteCard(card.id))
      },
      renameBoard: (id, title) => guarded(() => api.updateBoard(id, { title })),
      openBoard: onOpenBoard,
      resized: (id, width) => void guarded(() => api.updateCard(id, { w: Math.round(width) })),
    }),
    [guarded, childrenOf, onOpenBoard],
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

  const columnUnder = useCallback(
    (node: Node): string | null => {
      if (node.type !== 'card') return null
      // Internal nodes always carry the measured size; user nodes may not yet.
      const size = (id: string) => flow.getInternalNode(id)?.measured ?? {}
      const w = size(node.id).width ?? node.width ?? 0
      const h = size(node.id).height ?? 0
      const cx = node.position.x + w / 2
      const cy = node.position.y + Math.min(h / 2, 40)
      for (const n of flow.getNodes()) {
        if (n.type !== 'column' || n.id === node.id) continue
        const nw = size(n.id).width ?? n.width ?? 0
        const nh = size(n.id).height ?? 0
        if (cx >= n.position.x && cx <= n.position.x + nw && cy >= n.position.y && cy <= n.position.y + nh) return n.id
      }
      return null
    },
    [flow],
  )

  const onNodeDragStart = useCallback(() => {
    dragging.current = true
  }, [])

  const onNodeDrag: OnNodeDrag = useCallback(
    (_event, node, dragged) => setDropTarget(dragged.length === 1 ? columnUnder(node) : null),
    [columnUnder],
  )

  const onNodeDragStop: OnNodeDrag = useCallback(
    (event, node, dragged) => {
      dragging.current = false
      setDropTarget(null)
      const target = dragged.length === 1 ? columnUnder(node) : null
      const work = async () => {
        if (target) {
          const clientY = 'clientY' in event ? event.clientY : event.changedTouches[0]?.clientY ?? 0
          const items = Array.from(document.querySelectorAll(`[data-column="${target}"] [data-child]`))
          const index = items.filter((el) => {
            const r = el.getBoundingClientRect()
            return r.top + r.height / 2 < clientY
          }).length
          await api.moveCard(node.id, { column: target, index })
        } else {
          await Promise.all(
            dragged.map((n) => api.moveCard(n.id, { x: Math.round(n.position.x), y: Math.round(n.position.y) })),
          )
        }
      }
      void guarded(work)
      if (deferred.current) {
        setState(deferred.current)
        deferred.current = null
      }
    },
    [columnUnder, guarded],
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
    async (spec: Record<string, unknown>, edit = false) => {
      try {
        const card = await api.addCard(boardId, { ...centre(), ...spec })
        if (edit) setEditId(card.id)
      } catch (e) {
        onError((e as Error).message)
      }
    },
    [boardId, centre, onError],
  )

  const upload = useCallback(
    async (files: File[], at?: { x: number; y: number }) => {
      for (const [i, file] of files.entries()) {
        if (!file.type.startsWith('image/')) {
          onError(`${file.name}: drop images here. For audio, paste the file's path (⌥⌘C in Finder).`)
          continue
        }
        const spot = at ?? centre()
        await guarded(() => api.uploadImage(boardId, file, { x: spot.x + i * 24, y: spot.y + i * 24 }))
      }
    },
    [boardId, centre, guarded, onError],
  )

  // Paste: an image becomes an image card, a URL a link, an audio path an audio card, text a note.
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const active = document.activeElement
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA')) return
      const files = Array.from(e.clipboardData?.files ?? [])
      if (files.length) {
        e.preventDefault()
        void upload(files)
        return
      }
      const text = e.clipboardData?.getData('text/plain')?.trim()
      if (!text) return
      e.preventDefault()
      if (/^https?:\/\/\S+$/.test(text)) void add({ kind: 'link', url: text })
      else if (/^\/\S.*\.(mp3|wav|m4a|aac|flac|ogg|aif|aiff)$/i.test(text)) void add({ kind: 'audio', path: text })
      else void add({ kind: 'note', text })
    }
    window.addEventListener('paste', onPaste)
    return () => window.removeEventListener('paste', onPaste)
  }, [add, upload])

  const onDoubleClick = (e: React.MouseEvent) => {
    if (!(e.target as HTMLElement).classList.contains('react-flow__pane')) return
    const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY })
    void add({ kind: 'note', text: '', x: Math.round(p.x), y: Math.round(p.y) }, true)
  }

  const onDrop = (e: React.DragEvent) => {
    const files = Array.from(e.dataTransfer.files)
    if (!files.length) return
    e.preventDefault()
    const p = flow.screenToFlowPosition({ x: e.clientX, y: e.clientY })
    void upload(files, { x: Math.round(p.x), y: Math.round(p.y) })
  }

  const context: BoardContextValue = { cards, childrenOf, editId, setEditId, touched, dropTarget, actions }

  return (
    <BoardContext.Provider value={context}>
      <div
        className="canvas"
        ref={wrapper}
        onDoubleClick={onDoubleClick}
        onDragOver={(e) => e.dataTransfer.types.includes('Files') && e.preventDefault()}
        onDrop={onDrop}
      >
        <Toolbar
          onAdd={(spec, edit) => void add(spec, edit)}
          onImages={(files) => void upload(files)}
          onBoard={async (title) => {
            await guarded(async () => {
              await api.createBoard(title, boardId)
            })
          }}
        />
        <ReactFlow
          nodes={nodes}
          edges={[]}
          nodeTypes={nodeTypes}
          onNodesChange={onNodesChange}
          onNodeDragStart={onNodeDragStart}
          onNodeDrag={onNodeDrag}
          onNodeDragStop={onNodeDragStop}
          onPaneClick={() => setEditId(null)}
          zoomOnDoubleClick={false}
          deleteKeyCode={null}
          selectionOnDrag
          panOnScroll
          panOnDrag={[1, 2]}
          minZoom={0.2}
          maxZoom={2}
          colorMode="system"
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={24} size={1.2} />
          <Controls showInteractive={false} position="bottom-right" />
        </ReactFlow>
        {state && !state.cards.length && (
          <div className="empty-board">
            <p>An empty board.</p>
            <p className="muted">Double-click anywhere to write, paste a link or an image, or ask an agent to lay out a plan.</p>
          </div>
        )}
      </div>
    </BoardContext.Provider>
  )
}
