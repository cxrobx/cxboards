// Settings (⌘, the sidebar's Settings button, or CXBoards ▸ Settings…): this browser's preferences.

import { SCROLL_SPEED, setScrollSpeed, useScrollSpeed } from './prefs'

export function SettingsPanel({ onClose }: { onClose: () => void }) {
  const speed = useScrollSpeed()
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="panel dialog settings">
        <header>
          <h2>Settings</h2>
          <button className="ghost" onClick={onClose}>
            Close
          </button>
        </header>
        <div className="dialog-body">
          <label className="setting">
            <span className="setting-name">Scroll speed</span>
            <input
              type="range"
              min={SCROLL_SPEED.min}
              max={SCROLL_SPEED.max}
              step={SCROLL_SPEED.step}
              value={speed}
              onChange={(e) => setScrollSpeed(Math.round(Number(e.target.value) * 10) / 10)}
              autoFocus
            />
            <span className="setting-value">{speed.toFixed(1)}×</span>
            <button className="ghost" disabled={speed === SCROLL_SPEED.fallback} onClick={() => setScrollSpeed(SCROLL_SPEED.fallback)}>
              Reset
            </button>
          </label>
          <p className="muted">
            How far a two-finger scroll moves the board. At 1× it follows your fingers exactly. Pinch still zooms.
          </p>
        </div>
      </div>
    </div>
  )
}
