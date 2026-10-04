// Per-browser preferences (localStorage, like the sidebar's), read live by whoever uses them.

import { useSyncExternalStore } from 'react'

const SCROLL_KEY = 'cxboards.scroll-speed'
const EVENT = 'cxboards:settings'

/** How far a two-finger scroll moves the board, per pixel the fingers move. */
export const SCROLL_SPEED = { min: 0.5, max: 3, step: 0.1, fallback: 1 }

function readScrollSpeed(): number {
  try {
    const v = Number(localStorage.getItem(SCROLL_KEY))
    if (v >= SCROLL_SPEED.min && v <= SCROLL_SPEED.max) return v
  } catch {
    // private window or blocked storage: the default
  }
  return SCROLL_SPEED.fallback
}

export function setScrollSpeed(v: number) {
  try {
    if (v === SCROLL_SPEED.fallback) localStorage.removeItem(SCROLL_KEY)
    else localStorage.setItem(SCROLL_KEY, String(v))
  } catch {
    // not remembered, but still applied below for this window
  }
  current = v
  window.dispatchEvent(new Event(EVENT))
}

let current = readScrollSpeed()

function subscribe(onChange: () => void) {
  // Another window changing it arrives as a storage event.
  const onStorage = (e: StorageEvent) => {
    if (e.key !== SCROLL_KEY) return
    current = readScrollSpeed()
    onChange()
  }
  window.addEventListener(EVENT, onChange)
  window.addEventListener('storage', onStorage)
  return () => {
    window.removeEventListener(EVENT, onChange)
    window.removeEventListener('storage', onStorage)
  }
}

export function useScrollSpeed(): number {
  return useSyncExternalStore(subscribe, () => current)
}
