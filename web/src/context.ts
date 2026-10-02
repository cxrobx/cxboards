import { createContext, useContext } from 'react'
import type { Card } from './api'

export interface BoardActions {
  update: (id: string, patch: Record<string, unknown>) => Promise<void>
  move: (id: string, body: Record<string, unknown>) => Promise<void>
  remove: (card: Card) => Promise<void>
  renameBoard: (boardId: string, title: string) => Promise<void>
  openBoard: (boardId: string) => void
  resized: (id: string, width: number) => void
}

export interface BoardContextValue {
  cards: Map<string, Card>
  childrenOf: Map<string, Card[]>
  editId: string | null
  setEditId: (id: string | null) => void
  touched: Set<string>
  dropTarget: string | null
  actions: BoardActions
}

export const BoardContext = createContext<BoardContextValue | null>(null)

export function useBoard(): BoardContextValue {
  const value = useContext(BoardContext)
  if (!value) throw new Error('useBoard outside a board')
  return value
}

export const COLORS = ['', '#E0A33A', '#CB4B16', '#859900', '#2AA198', '#6C71C4', '#D33682']
