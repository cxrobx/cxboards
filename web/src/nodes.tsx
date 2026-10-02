// The cards themselves: how each kind looks, edits, and sits in a column.

import { NodeResizeControl, ResizeControlVariant, type NodeProps } from '@xyflow/react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { Card, TodoItem } from './api'
import { COLORS, useBoard } from './context'

marked.setOptions({ breaks: true, gfm: true })

function Markdown({ text }: { text: string }) {
  const html = DOMPurify.sanitize(marked.parse(text, { async: false }) as string)
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />
}

function todoToText(items: TodoItem[]): string {
  return items.map((i) => `${i.done ? '[x] ' : ''}${i.text}`).join('\n')
}

function textToTodo(text: string): TodoItem[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const done = /^\[x\]\s*/i.test(line)
      return { text: line.replace(/^\[[x ]?\]\s*/i, ''), done }
    })
}

/** Grow a textarea to fit what's in it. */
function autosize(el: HTMLTextAreaElement | null) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight + 2}px`
}

function Editor({ card, onDone }: { card: Card; onDone: () => void }) {
  const { actions } = useBoard()
  const [text, setText] = useState(card.text)
  const [extra, setExtra] = useState(
    card.kind === 'todo' ? todoToText(card.data.items ?? []) : card.kind === 'link' ? card.data.url ?? '' : '',
  )
  const area = useRef<HTMLTextAreaElement>(null)
  useEffect(() => {
    autosize(area.current)
    area.current?.focus()
    area.current?.setSelectionRange(area.current.value.length, area.current.value.length)
  }, [])

  const save = async () => {
    const patch: Record<string, unknown> = {}
    if (text !== card.text) patch.text = text
    if (card.kind === 'todo') patch.items = textToTodo(extra)
    if (card.kind === 'link' && extra.trim() && extra.trim() !== card.data.url) patch.url = extra.trim()
    onDone()
    if (Object.keys(patch).length) await actions.update(card.id, patch)
  }
  const onKey = (e: KeyboardEvent) => {
    if (e.key === 'Escape') onDone()
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) void save()
  }
  const blurOutside = (e: React.FocusEvent<HTMLDivElement>) => {
    if (!e.currentTarget.contains(e.relatedTarget as Node | null)) void save()
  }

  const labels: Record<string, string> = {
    note: 'Write in markdown…',
    todo: 'Title (optional)',
    link: 'A comment (optional)',
    image: 'Caption',
    audio: 'Notes on this bounce',
    column: 'Column title',
  }
  return (
    <div className="editor nodrag nowheel" onBlur={blurOutside} onKeyDown={onKey}>
      {card.kind === 'link' && (
        <input className="field" value={extra} placeholder="https://…" onChange={(e) => setExtra(e.target.value)} />
      )}
      {card.kind === 'column' || card.kind === 'todo' || card.kind === 'image' ? (
        <input
          className="field"
          autoFocus
          value={text}
          placeholder={labels[card.kind]}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && card.kind !== 'todo' && void save()}
        />
      ) : (
        <textarea
          ref={area}
          className="field"
          value={text}
          placeholder={labels[card.kind]}
          onChange={(e) => {
            setText(e.target.value)
            autosize(e.target)
          }}
        />
      )}
      {card.kind === 'todo' && (
        <textarea
          ref={area}
          className="field"
          value={extra}
          placeholder={'One item per line\n[x] marks one done'}
          onChange={(e) => {
            setExtra(e.target.value)
            autosize(e.target)
          }}
        />
      )}
      <div className="editor-hint">⌘↵ save · esc cancel</div>
    </div>
  )
}

function TodoList({ card }: { card: Card }) {
  const { actions } = useBoard()
  const items: TodoItem[] = card.data.items ?? []
  const toggle = (i: number) => {
    const next = items.map((item, j) => (j === i ? { ...item, done: !item.done } : item))
    void actions.update(card.id, { items: next })
  }
  return (
    <>
      {card.text && <div className="card-title">{card.text}</div>}
      <ul className="todo">
        {items.map((item, i) => (
          <li key={i} className={item.done ? 'done' : ''}>
            <input type="checkbox" className="nodrag" checked={item.done} onChange={() => toggle(i)} />
            <span>{item.text}</span>
          </li>
        ))}
        {!items.length && <li className="muted">Double-click to add items</li>}
      </ul>
    </>
  )
}

export function CardBody({ card }: { card: Card }) {
  const { editId, setEditId, actions } = useBoard()
  if (editId === card.id) return <Editor card={card} onDone={() => setEditId(null)} />
  const d = card.data
  switch (card.kind) {
    case 'note':
      return card.text ? <Markdown text={card.text} /> : <div className="muted">Double-click to write</div>
    case 'todo':
      return <TodoList card={card} />
    case 'link':
      return (
        <div className="link">
          {d.image && <img className="thumb" src={d.image} alt="" draggable={false} />}
          <a className="link-title nodrag" href={d.url} target="_blank" rel="noreferrer">
            {d.title || d.url}
          </a>
          {d.description && <div className="desc">{d.description}</div>}
          <div className="site">{d.site || new URL(d.url).hostname}</div>
          {card.text && <Markdown text={card.text} />}
        </div>
      )
    case 'image':
      return (
        <div className="image">
          <img src={`/media/${d.file}`} alt={card.text} draggable={false} />
          {card.text && <div className="caption">{card.text}</div>}
        </div>
      )
    case 'audio':
      return (
        <div className="audio">
          <div className="card-title">♪ {d.name}</div>
          <audio className="nodrag" controls preload="none" src={`/api/cards/${card.id}/audio`} />
          {card.text && <Markdown text={card.text} />}
          <div className="site" title={d.path}>
            {d.path}
          </div>
        </div>
      )
    case 'board':
      return (
        <div className="board-card" onDoubleClick={() => card.board && actions.openBoard(card.board.id)}>
          <div className="board-glyph">▦</div>
          <div className="card-title">{card.board?.title ?? 'Missing board'}</div>
          <div className="site">{card.board?.card_count ?? 0} cards · double-click</div>
        </div>
      )
    default:
      return null
  }
}

function Tools({ card, index }: { card: Card; index?: number }) {
  const { actions, setEditId } = useBoard()
  const nextColor = () => {
    const i = COLORS.indexOf(card.color ?? '')
    void actions.update(card.id, { color: COLORS[(i + 1) % COLORS.length] })
  }
  const rename = () => {
    const title = window.prompt('Board title', card.board?.title ?? '')
    if (title && card.board) void actions.renameBoard(card.board.id, title)
  }
  return (
    <div className="tools nodrag">
      {index !== undefined && (
        <>
          <button title="Move up" onClick={() => actions.move(card.id, { column: card.column_id, index: Math.max(0, index - 1) })}>↑</button>
          <button title="Move down" onClick={() => actions.move(card.id, { column: card.column_id, index: index + 1 })}>↓</button>
          <button title="Out of the column" onClick={() => actions.move(card.id, { column: '' })}>⇱</button>
        </>
      )}
      {card.kind === 'board' ? (
        <button title="Rename board" onClick={rename}>✎</button>
      ) : (
        <button title="Edit" onClick={() => setEditId(card.id)}>✎</button>
      )}
      <button title="Colour" onClick={nextColor}>
        <span className="swatch" style={{ background: card.color || 'transparent' }} />
      </button>
      <button title="Delete" onClick={() => actions.remove(card)}>✕</button>
    </div>
  )
}

function Resizer({ id }: { id: string }) {
  const { actions } = useBoard()
  return (
    <NodeResizeControl
      position="right"
      variant={ResizeControlVariant.Line}
      resizeDirection="horizontal"
      minWidth={160}
      maxWidth={900}
      className="resize-line"
      onResizeEnd={(_, params) => actions.resized(id, params.width)}
    />
  )
}

export function CardNode({ id, selected }: NodeProps) {
  const { cards, touched, setEditId } = useBoard()
  const card = cards.get(id)
  if (!card) return null
  const editable = card.kind !== 'board'
  return (
    <div
      className={`card kind-${card.kind}${selected ? ' selected' : ''}${touched.has(id) ? ' touched' : ''}`}
      style={card.color ? ({ '--accent': card.color } as React.CSSProperties) : undefined}
      onDoubleClick={() => editable && setEditId(id)}
    >
      <Resizer id={id} />
      <CardBody card={card} />
      <Tools card={card} />
      {touched.has(id) && <span className="agent-badge">agent</span>}
    </div>
  )
}

export function ColumnNode({ id, selected }: NodeProps) {
  const { cards, childrenOf, touched, editId, setEditId, dropTarget } = useBoard()
  const column = cards.get(id)
  if (!column) return null
  const kids = childrenOf.get(id) ?? []
  return (
    <div
      className={`column${selected ? ' selected' : ''}${touched.has(id) ? ' touched' : ''}${dropTarget === id ? ' drop' : ''}`}
      style={column.color ? ({ '--accent': column.color } as React.CSSProperties) : undefined}
      data-column={id}
    >
      <Resizer id={id} />
      <header onDoubleClick={() => setEditId(id)}>
        {editId === id ? <CardBody card={column} /> : column.text || <span className="muted">Untitled column</span>}
        <span className="count">{kids.length}</span>
      </header>
      <div className="column-body">
        {kids.map((kid, i) => (
          <div
            key={kid.id}
            data-child={kid.id}
            className={`card in-column kind-${kid.kind}${touched.has(kid.id) ? ' touched' : ''}`}
            style={kid.color ? ({ '--accent': kid.color } as React.CSSProperties) : undefined}
            onDoubleClick={(e) => {
              e.stopPropagation()
              if (kid.kind !== 'board') setEditId(kid.id)
            }}
          >
            <CardBody card={kid} />
            <Tools card={kid} index={i} />
            {touched.has(kid.id) && <span className="agent-badge">agent</span>}
          </div>
        ))}
        {!kids.length && <div className="column-empty">Drag cards here</div>}
      </div>
      <Tools card={column} />
      {touched.has(id) && <span className="agent-badge">agent</span>}
    </div>
  )
}
