import { createContext, useContext } from 'react'
import type { Card } from './api'

export interface BoardActions {
  update: (id: string, patch: Record<string, unknown>) => Promise<void>
  move: (id: string, body: Record<string, unknown>) => Promise<void>
  remove: (card: Card) => Promise<void>
  renameBoard: (boardId: string, title: string) => Promise<void>
  openBoard: (boardId: string) => void
  resized: (id: string, width: number) => void
  /** ⌘↵ while editing: save, then start the next note below (or next in the column). */
  addAfter: (card: Card) => void
  openFile: (card: Card, reveal?: boolean) => void
  /** Right-click on something that isn't a canvas node (a card inside a column). */
  menuFor: (event: React.MouseEvent, card: Card) => void
}

export interface BoardContextValue {
  cards: Map<string, Card>
  childrenOf: Map<string, Card[]>
  editId: string | null
  setEditId: (id: string | null) => void
  touched: Set<string>
  dropTarget: string | null
  focusId: string | null
  presenting: boolean
  actions: BoardActions
}

export const BoardContext = createContext<BoardContextValue | null>(null)

export function useBoard(): BoardContextValue {
  const value = useContext(BoardContext)
  if (!value) throw new Error('useBoard outside a board')
  return value
}

export const COLORS = ['', '#E0A33A', '#CB4B16', '#859900', '#2AA198', '#6C71C4', '#D33682']

export function humanSize(bytes?: number): string {
  if (!bytes && bytes !== 0) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let n = bytes
  let i = 0
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n < 10 && i ? n.toFixed(1) : Math.round(n)} ${units[i]}`
}
