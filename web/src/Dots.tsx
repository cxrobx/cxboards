// The canvas dot grid, drawn so panning never repaints it.
//
// React Flow's <Background> is a full-window SVG pattern whose offset changes on every pan frame,
// so the whole window was re-rasterised each frame (two thirds of a pan's raster time, more with a
// blurred backdrop under it). Here the dots are one tile, repeated on a layer a tile larger than the
// window, and a pan only moves that layer by the pan modulo one tile: a GPU transform, no paint.
// Only a zoom (the tile size changes) redraws it. Same placement and colour as <Background>.

import { useStore, useStoreApi, type Transform } from '@xyflow/react'
import { useEffect, useRef } from 'react'

const DOT = 'var(--xy-background-pattern-color, var(--xy-background-pattern-dots-color-default))'

export function Dots({ gap = 24, size = 1.2 }: { gap?: number; size?: number }) {
  const store = useStoreApi()
  const zoom = useStore((s) => s.transform[2])
  const layer = useRef<HTMLDivElement>(null)
  const g = gap * zoom || 1
  const r = (size * zoom) / 2

  useEffect(() => {
    // <Background> puts dot centres at x - g/2 + r (mod g); the layer starts one tile left of the
    // window and each tile's dot is at its centre, so the layer shifts by x - g + r (mod g).
    const off = (v: number) => (((v - g + r) % g) + g) % g
    let last: Transform | null = null
    const place = (t: Transform) => {
      if (t === last || !layer.current) return
      last = t
      layer.current.style.transform = `translate3d(${off(t[0])}px, ${off(t[1])}px, 0)`
    }
    place(store.getState().transform)
    return store.subscribe((s) => place(s.transform))
  }, [store, g, r])

  return (
    <div className="react-flow__background cx-dots" data-testid="rf__background">
      <div
        ref={layer}
        className="cx-dots-layer"
        style={{
          left: -g,
          top: -g,
          width: `calc(100% + ${2 * g}px)`,
          height: `calc(100% + ${2 * g}px)`,
          backgroundImage: `radial-gradient(circle at center, ${DOT} ${Math.max(0, r - 0.25)}px, transparent ${r + 0.25}px)`,
          backgroundSize: `${g}px ${g}px`,
        }}
      />
    </div>
  )
}
