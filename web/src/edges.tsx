// Lines between cards. A line runs between the two cards' borders (not fixed
// handles), straight or gently curved, with an optional label and arrowheads.
// Drag from a card's ● to another card to draw one.

import {
  BaseEdge,
  EdgeLabelRenderer,
  Handle,
  Position,
  useConnection,
  useInternalNode,
  type EdgeProps,
  type InternalNode,
} from '@xyflow/react'

export interface LineData extends Record<string, unknown> {
  label: string
  color: string | null
  style: 'solid' | 'dashed'
  curve: boolean
}

function centre(node: InternalNode) {
  const { x, y } = node.internals.positionAbsolute
  const w = node.measured.width ?? 0
  const h = node.measured.height ?? 0
  return { x: x + w / 2, y: y + h / 2, w, h }
}

/** Where the line from a node's centre towards (tx, ty) leaves the node's rectangle. */
function border(node: InternalNode, tx: number, ty: number) {
  const c = centre(node)
  const dx = tx - c.x
  const dy = ty - c.y
  if (!dx && !dy) return { x: c.x, y: c.y }
  const scale = Math.min(dx ? c.w / 2 / Math.abs(dx) : Infinity, dy ? c.h / 2 / Math.abs(dy) : Infinity)
  return { x: c.x + dx * scale, y: c.y + dy * scale }
}

export function FloatingEdge({ id, source, target, data, selected, markerEnd, markerStart }: EdgeProps) {
  const from = useInternalNode(source)
  const to = useInternalNode(target)
  if (!from || !to) return null
  const d = data as LineData
  const a = centre(from)
  const b = centre(to)
  const p1 = border(from, b.x, b.y)
  const p2 = border(to, a.x, a.y)
  let path: string
  let lx: number
  let ly: number
  if (d.curve) {
    const mx = (p1.x + p2.x) / 2
    const my = (p1.y + p2.y) / 2
    const nx = -(p2.y - p1.y) * 0.18
    const ny = (p2.x - p1.x) * 0.18
    path = `M${p1.x},${p1.y} Q${mx + nx},${my + ny} ${p2.x},${p2.y}`
    lx = mx + nx / 2
    ly = my + ny / 2
  } else {
    path = `M${p1.x},${p1.y} L${p2.x},${p2.y}`
    lx = (p1.x + p2.x) / 2
    ly = (p1.y + p2.y) / 2
  }
  const color = d.color || 'var(--line-ink)'
  return (
    <>
      <BaseEdge
        id={id}
        path={path}
        markerEnd={markerEnd}
        markerStart={markerStart}
        interactionWidth={18}
        style={{
          stroke: color,
          strokeWidth: selected ? 3 : 2,
          strokeDasharray: d.style === 'dashed' ? '7 6' : undefined,
        }}
      />
      {d.label && (
        <EdgeLabelRenderer>
          <div
            className={`edge-label nodrag nopan${selected ? ' selected' : ''}`}
            style={{ transform: `translate(-50%, -50%) translate(${lx}px, ${ly}px)` }}
          >
            {d.label}
          </div>
        </EdgeLabelRenderer>
      )}
    </>
  )
}

/** The ● you drag from to draw a line, and (only while a line is being drawn) a target
 * covering the whole card, so you can let go anywhere on it. */
export function ConnectHandles({ id, hidden }: { id: string; hidden?: boolean }) {
  const connection = useConnection()
  const targeting = connection.inProgress && connection.fromNode.id !== id
  return (
    <>
      {!hidden && <Handle type="source" position={Position.Right} className="connect-dot" title="Drag to another card to draw a line" />}
      <Handle
        type="target"
        position={Position.Left}
        className={`connect-target${targeting ? ' on' : ''}`}
        isConnectableStart={false}
      />
    </>
  )
}
