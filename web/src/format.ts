// Milanote's formatting keys, as markdown: ⌘B bold, ⌘I italic, ⌘K link, ⌘J
// highlight, ⌘E code, ⇧⌘X strike, ⇧⌘1 / ⇧⌘2 headings, ⇧⌘U bullets,
// ⇧⌘O numbers, ⇧⌘. quote. Returns the textarea's new value, or null if the
// key wasn't a formatting key.

import type { KeyboardEvent } from 'react'

function select(el: HTMLTextAreaElement, start: number, end: number) {
  requestAnimationFrame(() => {
    el.selectionStart = start
    el.selectionEnd = end
  })
}

function wrap(el: HTMLTextAreaElement, before: string, after = before, placeholder = ''): string {
  const { value, selectionStart: s, selectionEnd: e } = el
  const picked = value.slice(s, e) || placeholder
  // Already wrapped: unwrap.
  if (value.slice(s - before.length, s) === before && value.slice(e, e + after.length) === after) {
    select(el, s - before.length, e - before.length)
    return value.slice(0, s - before.length) + picked + value.slice(e + after.length)
  }
  select(el, s + before.length, s + before.length + picked.length)
  return value.slice(0, s) + before + picked + after + value.slice(e)
}

function prefixLines(el: HTMLTextAreaElement, prefix: string | ((i: number) => string), pattern: RegExp): string {
  const { value, selectionStart: s, selectionEnd: e } = el
  const start = value.lastIndexOf('\n', s - 1) + 1
  const endIdx = value.indexOf('\n', e)
  const stop = endIdx === -1 ? value.length : endIdx
  const lines = value.slice(start, stop).split('\n')
  const all = lines.every((l) => pattern.test(l))
  const next = lines
    .map((l, i) => (all ? l.replace(pattern, '') : (typeof prefix === 'function' ? prefix(i) : prefix) + l.replace(pattern, '')))
    .join('\n')
  select(el, start, start + next.length)
  return value.slice(0, start) + next + value.slice(stop)
}

export function formatKey(e: KeyboardEvent<HTMLTextAreaElement>): string | null {
  if (!(e.metaKey || e.ctrlKey)) return null
  const el = e.currentTarget
  const key = e.key.toLowerCase()
  let out: string | null = null
  if (!e.shiftKey && key === 'b') out = wrap(el, '**')
  else if (!e.shiftKey && key === 'i') out = wrap(el, '_')
  else if (!e.shiftKey && key === 'j') out = wrap(el, '==')
  else if (!e.shiftKey && key === 'e') out = wrap(el, '`')
  else if (!e.shiftKey && key === 'k') {
    const { value, selectionStart: s, selectionEnd: end } = el
    const text = value.slice(s, end) || 'link'
    out = `${value.slice(0, s)}[${text}](https://)${value.slice(end)}`
    const urlStart = s + text.length + 3
    select(el, urlStart, urlStart + 8)
  } else if (e.shiftKey && key === 'x') out = wrap(el, '~~')
  else if (e.shiftKey && (key === '1' || key === '!')) out = prefixLines(el, '# ', /^#{1,6}\s/)
  else if (e.shiftKey && (key === '2' || key === '@')) out = prefixLines(el, '## ', /^#{1,6}\s/)
  else if (e.shiftKey && key === 'u') out = prefixLines(el, '- ', /^[-*]\s/)
  else if (e.shiftKey && key === 'o') out = prefixLines(el, (i) => `${i + 1}. `, /^\d+\.\s/)
  else if (e.shiftKey && (key === '.' || key === '>')) out = prefixLines(el, '> ', /^>\s?/)
  if (out !== null) e.preventDefault()
  return out
}
