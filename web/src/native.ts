// Inside CXBoards.app the window has no title bar of its own (borderless, like Onyx): the page's
// top band and its [data-drag] areas (the board header, the sidebar's brand row) are the title bar.
// A web view swallows the mouse, so a press there is handed to the app, which drags the window by
// it; a double-click there zooms (or minimizes) as Desktop & Dock says. Controls keep their clicks.
// In a browser none of this runs.

type Handler = { postMessage: (body: unknown) => void }

const handler: Handler | undefined = (window as unknown as { webkit?: { messageHandlers?: { cxDrag?: Handler } } })
  .webkit?.messageHandlers?.cxDrag

export const inApp = !!handler

const KEEP =
  'a,button,input,textarea,select,summary,label,[contenteditable],[draggable=true],[data-nodrag],' +
  '.react-flow,.menu,.overlay,.toast,.tray,.toolbar,video,audio,iframe'
const BAND = 28

/** 2 = the title band (double-click zooms there), 1 = another drag area, 0 = the page's own. */
function dragAt(e: MouseEvent): 0 | 1 | 2 {
  const t = e.target
  if (!(t instanceof Element) || t.closest(KEEP)) return 0
  if (e.clientY < BAND) return 2
  return t.closest('[data-drag]') ? 1 : 0
}

export function installWindowDrag() {
  if (!handler) return
  let double: [number, number] | null = null
  document.addEventListener('mousedown', (e) => {
    const where = dragAt(e)
    if (e.button !== 0 || !where) return
    e.preventDefault() // no text selection, no focus change
    if (e.detail === 1) handler.postMessage({})
    else if (e.detail === 2 && where === 2) double = [e.clientX, e.clientY]
  })
  // As Tauri does on macOS: the double-click is sent on its mouse-up, only if the pointer didn't move.
  document.addEventListener('mouseup', (e) => {
    const d = double
    double = null
    if (e.button === 0 && e.detail === 2 && d && d[0] === e.clientX && d[1] === e.clientY && dragAt(e) === 2) {
      handler.postMessage({ double: true })
    }
  })
}
