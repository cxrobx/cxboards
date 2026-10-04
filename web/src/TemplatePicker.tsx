// New board: blank, one of Chris's own template boards, or a template from the library
// (templates/<category>/<slug>.yaml, served by /api/templates), browsed by use case or searched.

import { useEffect, useMemo, useRef, useState } from 'react'
import { api, type Board, type LibraryCategory, type TemplatePreview, type TemplateSummary } from './api'

type Choice = { kind: 'blank' } | { kind: 'library'; t: TemplateSummary } | { kind: 'yours'; b: Board }

const RECENT_KEY = 'cxboards.recent-templates'

function recent(): string[] {
  try {
    return JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]') as string[]
  } catch {
    return []
  }
}

function remember(slug: string) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify([slug, ...recent().filter((s) => s !== slug)].slice(0, 8)))
  } catch {
    /* a convenience */
  }
}

/** The template's top level as boxes: columns with their lines, notes, lists, boards. */
function Preview({ boxes }: { boxes: TemplatePreview[] }) {
  if (!boxes.length) return <svg className="tpl-preview" />
  const x0 = Math.min(...boxes.map((b) => b.x))
  const y0 = Math.min(...boxes.map((b) => b.y))
  const w = Math.max(...boxes.map((b) => b.x + b.w)) - x0
  const h = Math.max(...boxes.map((b) => b.y + b.h)) - y0
  const side = Math.max(w, h * 1.6) // keep very tall or very wide boards readable in a 16:10 tile
  return (
    <svg className="tpl-preview" viewBox={`${x0 - 20} ${y0 - 20} ${side + 40} ${side / 1.6 + 40}`} aria-hidden="true">
      {boxes.map((b, i) => (
        <g key={i} className={`tpl-box ${b.kind}`}>
          <rect x={b.x} y={b.y} width={b.w} height={b.h} rx={10} style={b.color ? { stroke: b.color } : undefined} />
          {b.color && <rect className="stripe" x={b.x} y={b.y} width={8} height={b.h} style={{ fill: b.color }} />}
          {b.kind === 'column' &&
            Array.from({ length: Math.min(b.children, 6) }, (_, j) => (
              <rect key={j} className="child" x={b.x + 14} y={b.y + 60 + j * ((b.h - 70) / Math.max(1, b.children))} width={b.w - 28} height={Math.max(18, (b.h - 70) / Math.max(1, b.children) - 10)} rx={6} />
            ))}
          {b.kind === 'board' && <rect className="child" x={b.x + 20} y={b.y + 20} width={44} height={44} rx={6} />}
        </g>
      ))}
    </svg>
  )
}

export function NewBoardDialog({
  yours,
  inside,
  browse,
  onCreate,
  onClose,
}: {
  yours: Board[]
  inside: string | null
  browse: boolean
  onCreate: (title: string, template: string | null) => void
  onClose: () => void
}) {
  const [title, setTitle] = useState('')
  const typed = useRef(false) // once a title is typed, picking a template no longer replaces it
  const [choice, setChoice] = useState<Choice>({ kind: 'blank' })
  const [categories, setCategories] = useState<LibraryCategory[]>([])
  const [all, setAll] = useState<TemplateSummary[]>([])
  const [found, setFound] = useState<TemplateSummary[] | null>(null)
  const [query, setQuery] = useState('')
  const recents = useMemo(() => recent(), [])
  const [shelf, setShelf] = useState<string>(browse ? (recents.length ? 'recent' : 'music') : 'blank')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .templates()
      .then((lib) => {
        setCategories(lib.categories)
        setAll(lib.templates)
      })
      .catch((e) => setError((e as Error).message))
  }, [])

  // Typing searches the whole library (ranked on the server: name and use first, then contents).
  useEffect(() => {
    if (!query.trim()) {
      setFound(null)
      return
    }
    const t = window.setTimeout(() => {
      api
        .templates(query)
        .then((lib) => setFound(lib.templates))
        .catch((e) => setError((e as Error).message))
    }, 120)
    return () => window.clearTimeout(t)
  }, [query])

  const bySlug = useMemo(() => new Map(all.map((t) => [t.slug, t])), [all])
  const shown: TemplateSummary[] =
    found ??
    (shelf === 'recent'
      ? recents.map((s) => bySlug.get(s)).filter((t): t is TemplateSummary => !!t)
      : all.filter((t) => t.category === shelf || t.also.includes(shelf)))
  const names = useMemo(() => new Map(categories.map((c) => [c.slug, c.name])), [categories])

  const pick = (next: Choice, name: string) => {
    setChoice(next)
    if (!typed.current) setTitle(next.kind === 'blank' ? '' : name)
  }
  const create = (c: Choice = choice, t: string = title) => {
    const name = t.trim() || (c.kind === 'library' ? c.t.name : c.kind === 'yours' ? c.b.title : '')
    if (!name) return
    if (c.kind === 'library') remember(c.t.slug)
    onCreate(name, c.kind === 'library' ? c.t.slug : c.kind === 'yours' ? c.b.id : null)
  }
  const chosen = choice.kind === 'library' ? choice.t.slug : choice.kind === 'yours' ? choice.b.id : 'blank'

  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <form
        className="panel dialog new-board"
        onSubmit={(e) => {
          e.preventDefault()
          create()
        }}
        onKeyDown={(e) => e.key === 'Escape' && onClose()}
      >
        <header>
          <h2>{inside ? `New board inside “${inside}”` : 'New board'}</h2>
          <input
            autoFocus
            className="field"
            placeholder="Title"
            value={title}
            onChange={(e) => {
              typed.current = true
              setTitle(e.target.value)
            }}
          />
        </header>
        <div className="tpl-browser">
          <nav className="tpl-shelves" aria-label="Template categories">
            <button type="button" className={shelf === 'blank' && !found ? 'on' : ''} onClick={() => (setShelf('blank'), setQuery(''), pick({ kind: 'blank' }, ''))}>
              Blank
            </button>
            {recents.length > 0 && (
              <button type="button" className={shelf === 'recent' && !found ? 'on' : ''} onClick={() => (setShelf('recent'), setQuery(''))}>
                Recent
              </button>
            )}
            {yours.length > 0 && (
              <button type="button" className={shelf === 'yours' && !found ? 'on' : ''} onClick={() => (setShelf('yours'), setQuery(''))}>
                Yours <span className="count">{yours.length}</span>
              </button>
            )}
            <div className="tpl-shelf-label">Library</div>
            {categories
              .filter((c) => c.count)
              .map((c) => (
                <button
                  type="button"
                  key={c.slug}
                  className={shelf === c.slug && !found ? 'on' : ''}
                  title={c.blurb}
                  onClick={() => (setShelf(c.slug), setQuery(''))}
                >
                  {c.name} <span className="count">{c.count}</span>
                </button>
              ))}
          </nav>
          <div className="tpl-main">
            <input
              className="field tpl-search"
              type="search"
              placeholder={`Search ${all.length} templates by use — “podcast outline”, “brand workshop”…`}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
            {error && <p className="muted">{error}</p>}
            {!found && shelf === 'blank' ? (
              <div className="tpl-empty">
                <p>An empty board. Name it above and press Create.</p>
                <p className="muted">Or pick a use case on the left; agents can start one too (“make me a podcast outline”).</p>
              </div>
            ) : !found && shelf === 'yours' ? (
              <div className="tpl-grid">
                {yours.map((b) => (
                  <button
                    type="button"
                    key={b.id}
                    className={`tpl-tile${chosen === b.id ? ' on' : ''}`}
                    onClick={() => pick({ kind: 'yours', b }, b.title)}
                    onDoubleClick={() => create({ kind: 'yours', b }, typed.current ? title : b.title)}
                  >
                    <span className="tpl-glyph">▦</span>
                    <strong>{b.title}</strong>
                    <span className="muted">{b.card_count} cards · your template</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="tpl-grid">
                {shown.map((t) => (
                  <button
                    type="button"
                    key={t.slug}
                    className={`tpl-tile${chosen === t.slug ? ' on' : ''}`}
                    title={t.use_when}
                    onClick={() => pick({ kind: 'library', t }, t.name)}
                    onDoubleClick={() => create({ kind: 'library', t }, typed.current ? title : t.name)}
                  >
                    <Preview boxes={t.preview} />
                    <strong>{t.name}</strong>
                    <span className="tpl-use">{t.use_when}</span>
                    {(found || shelf === 'recent') && <span className="tpl-cat">{names.get(t.category) ?? t.category}</span>}
                  </button>
                ))}
                {!shown.length && <p className="muted">{found ? 'Nothing matches. Try fewer words.' : 'Nothing here yet.'}</p>}
              </div>
            )}
          </div>
        </div>
        <footer>
          <span className="muted tpl-choice">
            {choice.kind === 'library'
              ? `${choice.t.name} · ${choice.t.card_count} cards`
              : choice.kind === 'yours'
                ? `${choice.b.title} · your template`
                : 'Blank board'}
          </span>
          <button type="button" className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button className="primary" disabled={!title.trim() && choice.kind === 'blank'}>
            Create
          </button>
        </footer>
      </form>
    </div>
  )
}
