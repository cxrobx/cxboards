// The UI's view of the CXBoards HTTP API (src/cxboards/app.py).

export type Kind = 'note' | 'todo' | 'link' | 'image' | 'audio' | 'column' | 'board'

export interface TodoItem {
  text: string
  done: boolean
}

export interface Card {
  id: string
  board_id: string
  kind: Kind
  column_id: string | null
  position: number
  x: number
  y: number
  w: number
  h: number
  z: number
  text: string
  data: Record<string, any>
  color: string | null
  updated_by: 'chris' | 'agent' | 'system'
  updated_at: string
  board?: { id: string; title: string; card_count: number } | null
}

export interface Board {
  id: string
  title: string
  description: string
  parent_id: string | null
  rev: number
  export_slug: string
  updated_at: string
  card_count?: number
}

export interface BoardState {
  board: Board
  cards: Card[]
  breadcrumbs: { id: string; title: string }[]
}

export interface ChangeEvent {
  board_id: string
  rev: number
  card_ids: string[]
  actor: 'chris' | 'agent' | 'system'
}

const WRITE = { 'Content-Type': 'application/json', 'X-CXBoards': '1' }

async function req<T>(method: string, path: string, body?: unknown): Promise<T> {
  const resp = await fetch(path, {
    method,
    headers: method === 'GET' ? undefined : WRITE,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!resp.ok) {
    let message = resp.statusText
    try {
      message = (await resp.json()).error ?? message
    } catch {
      /* not JSON */
    }
    throw new Error(message)
  }
  return resp.json() as Promise<T>
}

export const api = {
  boards: () => req<Board[]>('GET', '/api/boards'),
  board: (id: string) => req<BoardState>('GET', `/api/boards/${id}`),
  createBoard: (title: string, parent?: string) => req<Board>('POST', '/api/boards', { title, parent }),
  updateBoard: (id: string, patch: { title?: string; description?: string }) =>
    req<Board>('PATCH', `/api/boards/${id}`, patch),
  deleteBoard: (id: string) => req<{ ok: boolean }>('DELETE', `/api/boards/${id}`),
  addCard: (boardId: string, spec: Record<string, unknown>) => req<Card>('POST', `/api/boards/${boardId}/cards`, spec),
  updateCard: (id: string, patch: Record<string, unknown>) => req<Card>('PATCH', `/api/cards/${id}`, patch),
  moveCard: (id: string, body: Record<string, unknown>) => req<Card>('POST', `/api/cards/${id}/move`, body),
  deleteCard: (id: string) => req<{ ok: boolean }>('DELETE', `/api/cards/${id}`),
  async uploadImage(boardId: string, file: File, at?: { x: number; y: number }): Promise<Card> {
    const form = new FormData()
    form.append('file', file)
    if (at) {
      form.append('x', String(Math.round(at.x)))
      form.append('y', String(Math.round(at.y)))
    }
    const resp = await fetch(`/api/boards/${boardId}/images`, { method: 'POST', headers: { 'X-CXBoards': '1' }, body: form })
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).error ?? resp.statusText)
    return resp.json()
  },
}
