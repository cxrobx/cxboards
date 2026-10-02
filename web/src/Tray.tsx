// The Unsorted tray: cards waiting to be placed (clips, an agent's drops, a
// "send to Unsorted"). Drag one onto the canvas, or press Place.

import type { Card } from './api'
import { useBoard } from './context'
import { CardBody } from './nodes'

export const TRAY_MIME = 'application/x-cxboards-card'

export function TrayDrawer({ cards, onClose, onPlace }: { cards: Card[]; onClose: () => void; onPlace: (card: Card) => void }) {
  const { actions } = useBoard()
  return (
    <aside className="tray">
      <header>
        <strong>Unsorted</strong>
        <span className="muted">{cards.length}</span>
        <button className="ghost" onClick={onClose}>
          Hide
        </button>
      </header>
      <p className="muted tray-hint">Drag a card onto the board to place it.</p>
      <div className="tray-list">
        {cards.map((card) => (
          <div
            key={card.id}
            className={`card in-tray kind-${card.kind}`}
            draggable
            onDragStart={(e) => {
              e.dataTransfer.setData(TRAY_MIME, card.id)
              e.dataTransfer.effectAllowed = 'move'
            }}
            onContextMenu={(e) => {
              e.preventDefault()
              actions.menuFor(e, card)
            }}
          >
            <CardBody card={card} />
            <button className="chip place" onClick={() => onPlace(card)}>
              Place
            </button>
          </div>
        ))}
        {!cards.length && <p className="muted">Nothing waiting.</p>}
      </div>
    </aside>
  )
}
