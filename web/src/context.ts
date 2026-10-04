import { createContext, useContext } from 'react'
import type { Card } from './api'

export interface BoardActions {
  update: (id: string, patch: Record<string, unknown>) => Promise<void>
  move: (id: string, body: Record<string, unknown>) => Promise<void>
  remove: (card: Card) => Promise<void>
  renameBoard: (boardId: string, title: string) => Promise<void>
  openBoard: (boardId: string) => void
  /** A resize ended. `tall` = the height was dragged too, so it's kept (as a minimum). */
  resized: (id: string, box: { x: number; y: number; width: number; height: number }, tall: boolean) => void
  /** ⌘↵ while editing: save, then start the next note below (or next in the column). */
  addAfter: (card: Card) => void
  openFile: (card: Card, reveal?: boolean) => void
  /** Right-click on something that isn't a canvas node (a card inside a column). */
  menuFor: (event: React.MouseEvent, card: Card) => void
  lightbox: (card: Card) => void
  focusEdit: (card: Card) => void
  sketch: (card: Card) => void
  /** Open an animated card's drawing code. */
  motion: (card: Card) => void
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

export function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace('#', '')
  return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number]
}

export function swatchValue(hex: string, format: string): string {
  const [r, g, b] = hexToRgb(hex)
  if (format === 'rgb') return `rgb(${r}, ${g}, ${b})`
  if (format === 'hsl') {
    const [rr, gg, bb] = [r / 255, g / 255, b / 255]
    const max = Math.max(rr, gg, bb)
    const min = Math.min(rr, gg, bb)
    const l = (max + min) / 2
    let h = 0
    let s = 0
    if (max !== min) {
      const d = max - min
      s = l > 0.5 ? d / (2 - max - min) : d / (max + min)
      h = max === rr ? (gg - bb) / d + (gg < bb ? 6 : 0) : max === gg ? (bb - rr) / d + 2 : (rr - gg) / d + 4
      h *= 60
    }
    return `hsl(${Math.round(h)}, ${Math.round(s * 100)}%, ${Math.round(l * 100)}%)`
  }
  return hex.toUpperCase()
}

/** Black or white, whichever reads on this colour. */
export function inkOn(hex: string): string {
  const [r, g, b] = hexToRgb(hex)
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? '#111' : '#fff'
}
