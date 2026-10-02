// The UI's view of the CXBoards HTTP API (src/cxboards/app.py).

export type Kind =
  | 'note'
  | 'todo'
  | 'link'
  | 'image'
  | 'audio'
  | 'video'
  | 'file'
  | 'column'
  | 'board'
  | 'swatch'
  | 'sketch'

export interface TodoItem {
  text: string
  done: boolean
  indent?: number
}

export interface Label {
  id: string
  name: string
  color: string
}

export interface Connector {
  id: string
  board_id: string
  from_id: string
  to_id: string
  label: string
  color: string | null
  style: 'solid' | 'dashed'
  arrow: 'end' | 'both' | 'none'
  curve: boolean
}

export interface SearchResult {
  type: 'card' | 'board'
  kind?: Kind
  card_id?: string
  board_id: string
  board_title: string
  title: string
  snippet: string
}

export interface TrashItem {
  id: string
  board_id: string | null
  kind: string
  title: string
  deleted_at: string
  actor: string
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
  locked: boolean
  tray: boolean
  labels?: Label[]
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
  is_template: boolean
  updated_at: string
  card_count?: number
}

export interface BoardState {
  board: Board
  cards: Card[]
  connectors: Connector[]
  breadcrumbs: { id: string; title: string }[]
}

export interface ChangeEvent {
  board_id: string
  rev: number
  card_ids: string[]
  actor: 'chris' | 'agent' | 'system'
  history_id?: number
  summary?: string
}

export interface StepResult {
  id: number
  summary: string
  direction: 'undo' | 'redo'
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
  createBoard: (title: string, parent?: string, template?: string) =>
    req<Board>('POST', '/api/boards', { title, parent, template }),
  updateBoard: (id: string, patch: { title?: string; description?: string; is_template?: boolean }) =>
    req<Board>('PATCH', `/api/boards/${id}`, patch),
  deleteBoard: (id: string) => req<{ ok: boolean }>('DELETE', `/api/boards/${id}`),
  addCard: (boardId: string, spec: Record<string, unknown>) => req<Card>('POST', `/api/boards/${boardId}/cards`, spec),
  updateCard: (id: string, patch: Record<string, unknown>) => req<Card>('PATCH', `/api/cards/${id}`, patch),
  moveCard: (id: string, body: Record<string, unknown>) => req<Card>('POST', `/api/cards/${id}/move`, body),
  deleteCard: (id: string) => req<{ ok: boolean }>('DELETE', `/api/cards/${id}`),
  uploadImage: (boardId: string, file: File, at?: Place) => upload(`/api/boards/${boardId}/images`, file, at),
  uploadFile: (boardId: string, file: File, at?: Place) => upload(`/api/boards/${boardId}/files`, file, at),
  locate: (boardId: string, file: File, at?: Place) =>
    req<Card & { matches: string[] }>('POST', `/api/boards/${boardId}/locate`, {
      name: file.name,
      size: file.size,
      mtime: file.lastModified,
      ...placeFields(at),
    }),
  deleteCards: (ids: string[]) => req<{ trash_ids: string[] }>('POST', '/api/cards/delete', { card_ids: ids }),
  duplicate: (ids: string[], board?: string, at?: { x: number; y: number }) =>
    req<Card[]>('POST', '/api/cards/duplicate', { card_ids: ids, board, ...(at ? { x: Math.round(at.x), y: Math.round(at.y) } : {}) }),
  moveToBoard: (ids: string[], board: string, at?: { x: number; y: number }) =>
    req<{ moved: string[] }>('POST', '/api/cards/move-to-board', { card_ids: ids, board, ...(at ? { x: at.x, y: at.y } : {}) }),
  setPositions: (boardId: string, positions: Record<string, [number, number]>) =>
    req<{ moved: string[] }>('POST', `/api/boards/${boardId}/positions`, { positions }),
  group: (boardId: string, ids: string[], title: string) => req<Card>('POST', `/api/boards/${boardId}/group`, { card_ids: ids, title }),
  subBoard: (boardId: string, ids: string[], title: string) =>
    req<Card>('POST', `/api/boards/${boardId}/sub-board`, { card_ids: ids, title }),
  openFile: (id: string, reveal = false) => req<{ ok: boolean }>('POST', `/api/cards/${id}/open`, { reveal }),
  undo: (boardId: string) => req<StepResult>('POST', `/api/boards/${boardId}/undo`),
  redo: (boardId: string) => req<StepResult>('POST', `/api/boards/${boardId}/redo`),
  undoStep: (historyId: number) => req<StepResult>('POST', `/api/history/${historyId}/undo`),
  search: (q: string) => req<SearchResult[]>('GET', `/api/search?q=${encodeURIComponent(q)}`),
  trash: () => req<TrashItem[]>('GET', '/api/trash'),
  restore: (id: string) => req<{ board_id: string | null; kind: string }>('POST', `/api/trash/${id}/restore`),
  emptyTrash: () => req<{ emptied: number }>('DELETE', '/api/trash'),
  duplicateBoard: (id: string, opts: { template?: boolean; title?: string; parent?: string } = {}) =>
    req<Board>('POST', `/api/boards/${id}/duplicate`, opts),
  connect: (from: string, to: string, extra: Partial<Connector> = {}) =>
    req<Connector>('POST', '/api/connectors', { from, to, ...extra }),
  updateConnector: (id: string, patch: Partial<Connector>) => req<Connector>('PATCH', `/api/connectors/${id}`, patch),
  deleteConnector: (id: string) => req<{ ok: boolean }>('DELETE', `/api/connectors/${id}`),
  labels: () => req<(Label & { uses: number })[]>('GET', '/api/labels'),
  labelCards: (ids: string[], names: string[], remove = false) =>
    req<{ card_id: string; labels: Label[] }[]>('POST', '/api/cards/labels', { card_ids: ids, names, remove }),
  updateLabel: (id: string, patch: { name?: string; color?: string }) => req<Label>('PATCH', `/api/labels/${id}`, patch),
  deleteLabel: (id: string) => req<{ ok: boolean }>('DELETE', `/api/labels/${id}`),
  uploadAsset: async (file: File): Promise<{ file: string; url: string }> => {
    const form = new FormData()
    form.append('file', file)
    const resp = await fetch('/api/uploads', { method: 'POST', headers: { 'X-CXBoards': '1' }, body: form })
    if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).error ?? resp.statusText)
    return resp.json()
  },
  rotate: (id: string, degrees: number) => req<Card>('POST', `/api/cards/${id}/rotate`, { degrees }),
}

export type Place = { x?: number; y?: number; column?: string; unsorted?: boolean }

function placeFields(at?: Place): Record<string, unknown> {
  if (!at) return {}
  const out: Record<string, unknown> = {}
  if (at.x !== undefined && at.y !== undefined) {
    out.x = Math.round(at.x)
    out.y = Math.round(at.y)
  }
  if (at.column) out.column = at.column
  if (at.unsorted) out.unsorted = true
  return out
}

async function upload(path: string, file: File, at?: Place): Promise<Card> {
  const form = new FormData()
  form.append('file', file)
  for (const [k, v] of Object.entries(placeFields(at))) form.append(k, String(v))
  const resp = await fetch(path, { method: 'POST', headers: { 'X-CXBoards': '1' }, body: form })
  if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).error ?? resp.statusText)
  return resp.json()
}
