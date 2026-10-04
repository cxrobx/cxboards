// Ask: chat about the open board with Claude (on the subscription, via the server's
// headless `claude -p`). The agent can change the board through the cxboards tools;
// its changes land live with an Undo. Selected cards travel with the question.

import { useCallback, useEffect, useRef, useState } from 'react'
import type { Card } from './api'
import { Markdown } from './nodes'

interface Message {
  role: 'user' | 'assistant'
  text: string
  tools?: string[]
  cost?: number | null
  model?: string
  error?: string
  stopped?: boolean
  selection?: string[]
  live?: { label: string; active: boolean }[]
}

interface ChatSummary {
  id: string
  title: string
  updated_at: string
  n: number
}

interface Info {
  available: boolean
  models: Record<string, string>
  default: string
}

const MODEL_KEY = 'cxboards.chat-model'
const STARTERS = [
  'Lay out a session plan for this board',
  'Group the loose ideas into columns',
  "What's missing before I open FL?",
  'Summarise this board in three lines',
]

// A question started elsewhere (a card's "Animate…"): Ask opens with it typed in, for Chris to
// finish and send. The shell opens the panel on the event; the panel takes the draft when it's up.
let draft: string | null = null
export function askWith(text: string) {
  draft = text
  window.dispatchEvent(new CustomEvent('cxboards:ask'))
}

function readModel(fallback: string): string {
  try {
    return localStorage.getItem(MODEL_KEY) || fallback
  } catch {
    return fallback
  }
}

export function ChatPanel({
  boardId,
  boardTitle,
  selection,
  onClose,
}: {
  boardId: string
  boardTitle: string
  selection: () => Card[]
  onClose: () => void
}) {
  const [info, setInfo] = useState<Info | null>(null)
  const [model, setModel] = useState('sonnet')
  const [chats, setChats] = useState<ChatSummary[]>([])
  const [chatId, setChatId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [picked, setPicked] = useState<Card[]>([])
  const abort = useRef<AbortController | null>(null)
  const list = useRef<HTMLDivElement>(null)
  const box = useRef<HTMLTextAreaElement>(null)

  const loadChats = useCallback(async () => {
    const rows: ChatSummary[] = await fetch(`/api/boards/${boardId}/chats`).then((r) => r.json())
    setChats(rows)
    return rows
  }, [boardId])

  const openChat = useCallback(async (id: string | null) => {
    abort.current?.abort()
    setChatId(id)
    if (!id) return setMessages([])
    const chat = await fetch(`/api/chats/${id}`).then((r) => r.json())
    setMessages(chat.messages ?? [])
  }, [])

  useEffect(() => {
    fetch('/api/chat/info')
      .then((r) => r.json())
      .then((i: Info) => {
        setInfo(i)
        setModel(readModel(i.default))
      })
    void loadChats().then((rows) => openChat(rows[0]?.id ?? null))
    return () => abort.current?.abort()
  }, [loadChats, openChat])

  // What's selected on the board right now goes with the next question.
  useEffect(() => {
    const t = window.setInterval(() => setPicked(selection()), 500)
    return () => window.clearInterval(t)
  }, [selection])

  useEffect(() => {
    list.current?.scrollTo({ top: list.current.scrollHeight })
  }, [messages])

  useEffect(() => box.current?.focus(), [chatId])

  useEffect(() => {
    const take = () => {
      if (draft === null) return
      setInput(draft)
      draft = null
      window.setTimeout(() => {
        const el = box.current
        if (!el) return
        el.focus()
        el.setSelectionRange(el.value.length, el.value.length)
      }, 50)
    }
    take()
    window.addEventListener('cxboards:ask', take)
    return () => window.removeEventListener('cxboards:ask', take)
  }, [])

  const patchLast = (fn: (m: Message) => Message) =>
    setMessages((ms) => (ms.length ? [...ms.slice(0, -1), fn(ms[ms.length - 1])] : ms))

  const send = async (text: string) => {
    const message = text.trim()
    if (!message || busy) return
    const chosen = picked
    setInput('')
    setBusy(true)
    setMessages((ms) => [
      ...ms,
      { role: 'user', text: message, selection: chosen.map((c) => c.id) },
      { role: 'assistant', text: '', live: [] },
    ])
    const controller = new AbortController()
    abort.current = controller
    try {
      const resp = await fetch(`/api/boards/${boardId}/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CXBoards': '1' },
        body: JSON.stringify({ message, chat_id: chatId, model, selection: chosen.map((c) => c.id) }),
        signal: controller.signal,
      })
      if (!resp.ok || !resp.body) throw new Error((await resp.json().catch(() => ({}))).error ?? resp.statusText)
      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      for (;;) {
        const { value, done } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let cut: number
        while ((cut = buffer.indexOf('\n\n')) >= 0) {
          const block = buffer.slice(0, cut)
          buffer = buffer.slice(cut + 2)
          const kind = block.match(/^event: (.*)$/m)?.[1]
          const raw = block.match(/^data: (.*)$/m)?.[1]
          if (!kind || !raw) continue
          const data = JSON.parse(raw)
          if (kind === 'chat') {
            if (!chatId) setChatId(data.chat_id)
          } else if (kind === 'token') {
            patchLast((m) => ({ ...m, text: m.text + data.text }))
          } else if (kind === 'tool') {
            patchLast((m) => {
              const live = [...(m.live ?? [])]
              if (data.state === 'start') live.push({ label: data.label, active: true })
              else {
                const i = live.map((l) => l.label).lastIndexOf(data.label)
                if (i >= 0) live[i] = { ...live[i], active: false }
              }
              return { ...m, live }
            })
          } else if (kind === 'done') {
            patchLast((m) => ({ ...m, text: data.text || m.text, cost: data.cost, model, live: m.live?.map((l) => ({ ...l, active: false })) }))
          } else if (kind === 'error') {
            patchLast((m) => ({ ...m, error: data.message, live: m.live?.map((l) => ({ ...l, active: false })) }))
          }
        }
      }
    } catch (e) {
      if ((e as Error).name === 'AbortError') patchLast((m) => ({ ...m, stopped: true, live: m.live?.map((l) => ({ ...l, active: false })) }))
      else patchLast((m) => ({ ...m, error: (e as Error).message }))
    } finally {
      abort.current = null
      setBusy(false)
      void loadChats()
    }
  }

  const remove = async () => {
    if (!chatId || !window.confirm('Delete this chat?')) return
    await fetch(`/api/chats/${chatId}`, { method: 'DELETE', headers: { 'X-CXBoards': '1' } })
    const rows = await loadChats()
    void openChat(rows[0]?.id ?? null)
  }

  return (
    <aside className="chat" onKeyDown={(e) => e.stopPropagation()}>
      <header>
        <strong>Ask</strong>
        <select
          className="chat-history"
          value={chatId ?? ''}
          onChange={(e) => void openChat(e.target.value || null)}
          title="Earlier chats on this board"
        >
          <option value="">New chat</option>
          {chats.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <button className="ghost" title="New chat" onClick={() => void openChat(null)} disabled={busy}>
          ＋
        </button>
        {chatId && (
          <button className="ghost" title="Delete this chat" onClick={() => void remove()} disabled={busy}>
            🗑
          </button>
        )}
        <button className="ghost" title="Close (⌘/)" onClick={onClose}>
          ✕
        </button>
      </header>

      <div className="chat-list" ref={list}>
        {!messages.length && (
          <div className="chat-empty">
            <p>
              Ask about <strong>{boardTitle}</strong>, or have it change the board. What it does shows up live, and you
              can undo it.
            </p>
            {info && !info.available && <p className="chat-error">Claude Code isn't installed on this Mac, so Ask can't answer.</p>}
            <div className="starters">
              {STARTERS.map((s) => (
                <button key={s} className="chip" onClick={() => void send(s)}>
                  {s}
                </button>
              ))}
            </div>
          </div>
        )}
        {messages.map((m, i) =>
          m.role === 'user' ? (
            <div key={i} className="msg user">
              {m.text}
              {!!m.selection?.length && <div className="msg-meta">with {m.selection.length} selected card{m.selection.length === 1 ? '' : 's'}</div>}
            </div>
          ) : (
            <div key={i} className="msg assistant">
              {(m.live ?? m.tools?.map((label) => ({ label, active: false })) ?? []).map((t, j) => (
                <span key={j} className={`tool-pill${t.active ? ' active' : ''}`}>
                  {t.active ? '◌' : '✓'} {t.label}
                </span>
              ))}
              {m.text ? <Markdown text={m.text} /> : !m.error && !m.stopped && busy && i === messages.length - 1 ? <span className="thinking">Thinking…</span> : null}
              {m.error && <div className="chat-error">{m.error}</div>}
              {m.stopped && <div className="msg-meta">stopped</div>}
              {m.cost != null && (
                <div className="msg-meta">
                  {info?.models[m.model ?? ''] ?? m.model} · ${m.cost.toFixed(3)}
                </div>
              )}
            </div>
          ),
        )}
      </div>

      <footer>
        {!!picked.length && (
          <div className="chat-selection">
            {picked.length} selected card{picked.length === 1 ? '' : 's'} will go with your question
          </div>
        )}
        <textarea
          ref={box}
          className="field"
          rows={3}
          value={input}
          placeholder={busy ? 'Working on it…' : 'Ask, or tell it what to do with the board…'}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void send(input)
            }
          }}
        />
        <div className="chat-actions">
          <select
            value={model}
            onChange={(e) => {
              setModel(e.target.value)
              try {
                localStorage.setItem(MODEL_KEY, e.target.value)
              } catch {
                /* a convenience */
              }
            }}
            title="Model"
          >
            {Object.entries(info?.models ?? { sonnet: 'Sonnet' }).map(([id, name]) => (
              <option key={id} value={id}>
                {name}
              </option>
            ))}
          </select>
          <span className="hint">↵ send · ⇧↵ new line</span>
          {busy ? (
            <button className="ghost" onClick={() => abort.current?.abort()}>
              ■ Stop
            </button>
          ) : (
            <button className="primary" onClick={() => void send(input)} disabled={!input.trim()}>
              Send
            </button>
          )}
        </div>
      </footer>
    </aside>
  )
}
