// The cards themselves: how each kind looks, edits, and sits in a column.

import { NodeResizeControl, ResizeControlVariant, type NodeProps } from '@xyflow/react'
import DOMPurify from 'dompurify'
import { marked } from 'marked'
import { useEffect, useRef, useState, type KeyboardEvent } from 'react'
import type { Card, TodoItem } from './api'
import { COLORS, humanSize, useBoard } from './context'

marked.setOptions({ breaks: true, gfm: true })

export function Markdown({ text }: { text: string }) {
  const highlighted = text.replace(/==([^=\n]+)==/g, '<mark>$1</mark>')
  const html = DOMPurify.sanitize(marked.parse(highlighted, { async: false }) as string)
  return <div className="md" dangerouslySetInnerHTML={{ __html: html }} />
}

export function todoToText(items: TodoItem[]): string {
  return items.map((i) => `${'  '.repeat(i.indent ?? 0)}${i.done ? '[x] ' : ''}${i.text}`).join('\n')
}

export function textToTodo(text: string): TodoItem[] {
  return text
    .split('\n')
    .filter((line) => line.trim())
    .map((line) => {
      const lead = line.match(/^(\s*)/)?.[1] ?? ''
      const indent = Math.min(3, Math.floor(lead.replace(/\t/g, '  ').length / 2))
      const body = line.trim()
      const done = /^\[x\]\s*/i.test(body)
      return { text: body.replace(/^\[[x ]?\]\s*/i, ''), done, indent }
    })
}

/** Grow a textarea to fit what's in it. */
function autosize(el: HTMLTextAreaElement | null) {
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${el.scrollHeight + 2}px`
}

/** Tab / ⇧Tab indent or outdent the current line(s) of a textarea by two spaces. */
function indentLines(el: HTMLTextAreaElement, outdent: boolean): string {
  const { value, selectionStart, selectionEnd } = el
  const start = value.lastIndexOf('\n', selectionStart - 1) + 1
  const end = value.indexOf('\n', selectionEnd)
  const stop = end === -1 ? value.length : end
  const block = value.slice(start, stop)
  const next = block
    .split('\n')
    .map((line) => (outdent ? line.replace(/^ {1,2}/, '') : `  ${line}`))
    .join('\n')
  const updated = value.slice(0, start) + next + value.slice(stop)
  requestAnimationFrame(() => {
    const delta = next.length - block.length
    el.selectionStart = Math.max(start, selectionStart + (outdent ? Math.max(delta, -2) : 2))
    el.selectionEnd = selectionEnd + delta
  })
  return updated
}

function Editor({ card, onDone }: { card: Card; onDone: () => void }) {
  const { actions } = useBoard()
  const [text, setText] = useState(card.text)
  const [extra, setExtra] = useState(
    card.kind === 'todo' ? todoToText(card.data.items ?? []) : card.kind === 'link' ? card.data.url ?? '' : '',
  )
  const area = useRef<HTMLTextAreaElement>(null)
  const saved = useRef(false)
  useEffect(() => {
    autosize(area.current)
    area.current?.focus()
    area.current?.setSelectionRange(area.current.value.length, area.current.value.length)
  }, [])

  const save = async (thenNext = false) => {
    if (saved.current) return
    saved.current = true
    const patch: Record<string, unknown> = {}
    if (text !== card.text) patch.text = text
    if (card.kind === 'todo') patch.items = textToTodo(extra)
    if (card.kind === 'link' && extra.trim() && extra.trim() !== card.data.url) patch.url = extra.trim()
    onDone()
    if (Object.keys(patch).length) await actions.update(card.id, patch)
    if (thenNext) actions.addAfter(card)
  }
  const onKey = (e: KeyboardEvent) => {
    e.stopPropagation() // keep board shortcuts (Delete, arrows, ⌘Z) out of the text
    if (e.key === 'Escape') void save()
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault()
      void save(card.kind === 'note' || card.kind === 'todo')
    }
    if (e.key === 'Tab' && card.kind === 'todo' && e.target instanceof HTMLTextAreaElement && e.target === area.current) {
      e.preventDefault()
      setExtra(indentLines(e.target, e.shiftKey))
    }
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
    video: 'Notes',
    file: 'Notes',
    column: 'Column title',
    swatch: 'Name this colour',
    sketch: 'Caption',
  }
  const singleLine = ['column', 'todo', 'image', 'swatch', 'sketch'].includes(card.kind)
  return (
    <div className="editor nodrag nowheel" onBlur={blurOutside} onKeyDown={onKey}>
      {card.kind === 'link' && (
        <input className="field" value={extra} placeholder="https://…" onChange={(e) => setExtra(e.target.value)} />
      )}
      {singleLine ? (
        <input
          className="field"
          autoFocus
          value={text}
          placeholder={labels[card.kind]}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && !e.metaKey && card.kind !== 'todo' && void save()}
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
          placeholder={'One item per line\n[x] marks one done · Tab indents'}
          onChange={(e) => {
            setExtra(e.target.value)
            autosize(e.target)
          }}
        />
      )}
      <div className="editor-hint">
        {card.kind === 'note' || card.kind === 'todo' ? '⌘↵ next note · esc done' : 'esc done'}
      </div>
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
  const done = items.filter((i) => i.done).length
  return (
    <>
      {card.text && <div className="card-title">{card.text}</div>}
      <ul className="todo">
        {items.map((item, i) => (
          <li key={i} className={item.done ? 'done' : ''} style={{ paddingLeft: (item.indent ?? 0) * 18 }}>
            <input type="checkbox" className="nodrag" checked={item.done} onChange={() => toggle(i)} />
            <span>{item.text}</span>
          </li>
        ))}
        {!items.length && <li className="muted">Double-click to add items</li>}
      </ul>
      {items.length > 1 && (
        <div className="site">
          {done} of {items.length} done
        </div>
      )}
    </>
  )
}

function FileActions({ card }: { card: Card }) {
  const { actions } = useBoard()
  return (
    <div className="file-actions nodrag">
      <button onClick={() => actions.openFile(card)} title="Open in its app">
        Open
      </button>
      <button onClick={() => actions.openFile(card, true)} title="Show in Finder">
        Reveal
      </button>
      {card.data.copied && (
        <span className="badge" title="Couldn't find the original on disk, so CXBoards keeps a copy">
          copied
        </span>
      )}
    </div>
  )
}

function MediaError() {
  return <div className="media-missing">Not reachable. Is the drive mounted?</div>
}

function AudioCard({ card }: { card: Card }) {
  const { actions } = useBoard()
  const d = card.data
  const [missing, setMissing] = useState(false)
  return (
    <div className="audio">
      <div className="card-title">♪ {d.name}</div>
      {missing ? (
        <MediaError />
      ) : (
        <audio
          className="nodrag"
          controls
          preload="none"
          loop={!!d.loop}
          src={`/api/cards/${card.id}/file`}
          onError={() => setMissing(true)}
        />
      )}
      {card.text && <Markdown text={card.text} />}
      <div className="media-row nodrag">
        <button
          className={`chip${d.loop ? ' on' : ''}`}
          title="Loop"
          onClick={() => actions.update(card.id, { data: { loop: !d.loop } })}
        >
          ⟲ loop
        </button>
        <FileActions card={card} />
      </div>
      <div className="site" title={d.path}>
        {d.path}
      </div>
    </div>
  )
}

function VideoCard({ card }: { card: Card }) {
  const { actions } = useBoard()
  const d = card.data
  const [missing, setMissing] = useState(false)
  return (
    <div className="video">
      {missing ? (
        <MediaError />
      ) : (
        <video
          className="nodrag"
          controls
          preload="metadata"
          loop={!!d.loop}
          src={`/api/cards/${card.id}/file`}
          onError={() => setMissing(true)}
        />
      )}
      <div className="card-title">▶ {d.name}</div>
      {card.text && <Markdown text={card.text} />}
      <div className="media-row nodrag">
        <button className={`chip${d.loop ? ' on' : ''}`} onClick={() => actions.update(card.id, { data: { loop: !d.loop } })}>
          ⟲ loop
        </button>
        <FileActions card={card} />
      </div>
    </div>
  )
}

const EXT_LABEL: Record<string, string> = { flp: 'FL', als: 'ALS', rpp: 'RPP', pdf: 'PDF', md: 'MD' }

function FileCard({ card }: { card: Card }) {
  const d = card.data
  const ext = String(d.ext ?? '').toLowerCase()
  return (
    <div className="file">
      {ext === 'pdf' && (
        <iframe className="pdf nodrag nowheel" src={`/api/cards/${card.id}/file#toolbar=0&view=FitH`} title={d.name} />
      )}
      <div className="file-head">
        <span className="ext">{EXT_LABEL[ext] ?? (ext.toUpperCase() || 'FILE')}</span>
        <span className="card-title file-name" title={d.name}>
          {d.name}
        </span>
      </div>
      {card.text && <Markdown text={card.text} />}
      <div className="site" title={d.path}>
        {humanSize(d.size)} · {d.path}
      </div>
      <FileActions card={card} />
    </div>
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
      return <AudioCard card={card} />
    case 'video':
      return <VideoCard card={card} />
    case 'file':
      return <FileCard card={card} />
    case 'board':
      return (
        <div className="board-card" onDoubleClick={() => card.board && actions.openBoard(card.board.id)}>
          <div className="board-glyph">{d.shortcut ? '↪' : '▦'}</div>
          <div className="card-title">{card.board?.title ?? 'Missing board'}</div>
          <div className="site">
            {card.board?.card_count ?? 0} cards · {d.shortcut ? 'shortcut · ' : ''}double-click
          </div>
        </div>
      )
    default:
      return (
        <div className="muted" onDoubleClick={() => setEditId(card.id)}>
          {card.kind}
        </div>
      )
  }
}

function Tools({ card, index }: { card: Card; index?: number }) {
  const { actions, setEditId, presenting } = useBoard()
  if (presenting) return null
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
        <span className="swatch-dot" style={{ background: card.color || 'transparent' }} />
      </button>
      {!card.locked && (
        <button title="Delete (to the trash)" onClick={() => actions.remove(card)}>✕</button>
      )}
    </div>
  )
}

function Resizer({ id }: { id: string }) {
  const { actions, cards, presenting } = useBoard()
  if (presenting || cards.get(id)?.locked) return null
  return (
    <NodeResizeControl
      position="right"
      variant={ResizeControlVariant.Line}
      resizeDirection="horizontal"
      minWidth={120}
      maxWidth={1200}
      className="resize-line"
      onResizeEnd={(_, params) => actions.resized(id, params.width)}
    />
  )
}

function cardClass(card: Card, extra: string, touched: Set<string>, focusId: string | null): string {
  return [
    extra,
    `kind-${card.kind}`,
    touched.has(card.id) ? 'touched' : '',
    focusId === card.id ? 'focused' : '',
    card.locked ? 'locked' : '',
    card.data.fill && card.color ? 'filled' : '',
  ]
    .filter(Boolean)
    .join(' ')
}

const NO_DOUBLE_CLICK_EDIT = new Set(['board', 'audio', 'video', 'file'])

export function CardNode({ id, selected }: NodeProps) {
  const { cards, touched, setEditId, focusId, presenting, dropTarget } = useBoard()
  const card = cards.get(id)
  if (!card) return null
  return (
    <div
      className={cardClass(card, `card${selected ? ' selected' : ''}${dropTarget === id ? ' drop' : ''}`, touched, focusId)}
      style={card.color ? ({ '--accent': card.color } as React.CSSProperties) : undefined}
      onDoubleClick={() => !presenting && !NO_DOUBLE_CLICK_EDIT.has(card.kind) && setEditId(id)}
    >
      <Resizer id={id} />
      <CardBody card={card} />
      <Tools card={card} />
      {card.locked && (
        <span className="lock-badge" title="Locked">
          🔒
        </span>
      )}
      {touched.has(id) && <span className="agent-badge">agent</span>}
    </div>
  )
}

export function ColumnNode({ id, selected }: NodeProps) {
  const { cards, childrenOf, touched, editId, setEditId, dropTarget, focusId, actions, presenting } = useBoard()
  const column = cards.get(id)
  if (!column) return null
  const kids = childrenOf.get(id) ?? []
  const collapsed = !!column.data.collapsed
  return (
    <div
      className={cardClass(
        column,
        `column${selected ? ' selected' : ''}${dropTarget === id ? ' drop' : ''}${collapsed ? ' collapsed' : ''}`,
        touched,
        focusId,
      )}
      style={column.color ? ({ '--accent': column.color } as React.CSSProperties) : undefined}
      data-column={id}
    >
      <Resizer id={id} />
      <header onDoubleClick={() => !presenting && setEditId(id)}>
        <button
          className="collapse nodrag"
          title={collapsed ? 'Expand' : 'Collapse'}
          onClick={() => actions.update(id, { data: { collapsed: !collapsed } })}
        >
          {collapsed ? '▸' : '▾'}
        </button>
        <span className="column-title">
          {editId === id ? <CardBody card={column} /> : column.text || <span className="muted">Untitled column</span>}
        </span>
        <span className="count">{kids.length}</span>
      </header>
      {!collapsed && (
        <div className="column-body">
          {kids.map((kid, i) => (
            <div
              key={kid.id}
              data-child={kid.id}
              className={cardClass(kid, 'card in-column', touched, focusId)}
              style={kid.color ? ({ '--accent': kid.color } as React.CSSProperties) : undefined}
              onDoubleClick={(e) => {
                e.stopPropagation()
                if (!presenting && !NO_DOUBLE_CLICK_EDIT.has(kid.kind)) setEditId(kid.id)
              }}
              onContextMenu={(e) => {
                e.preventDefault()
                e.stopPropagation()
                actions.menuFor(e, kid)
              }}
            >
              <CardBody card={kid} />
              <Tools card={kid} index={i} />
              {kid.locked && <span className="lock-badge">🔒</span>}
              {touched.has(kid.id) && <span className="agent-badge">agent</span>}
            </div>
          ))}
          {!kids.length && <div className="column-empty">Drag cards here</div>}
        </div>
      )}
      <Tools card={column} />
      {column.locked && <span className="lock-badge">🔒</span>}
      {touched.has(id) && <span className="agent-badge">agent</span>}
    </div>
  )
}
