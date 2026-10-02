// The left rail: one button per card kind. Links, audio and boards ask for
// one line of input first; images open the file picker.

import { useRef, useState } from 'react'

type Ask = { kind: 'link' | 'audio' | 'board'; placeholder: string } | null

interface Props {
  onAdd: (spec: Record<string, unknown>, edit?: boolean) => void
  onImages: (files: File[]) => void
  onBoard: (title: string) => void
}

export function Toolbar({ onAdd, onImages, onBoard }: Props) {
  const [ask, setAsk] = useState<Ask>(null)
  const [value, setValue] = useState('')
  const picker = useRef<HTMLInputElement>(null)

  const submit = () => {
    const v = value.trim()
    if (!ask || !v) return
    if (ask.kind === 'link') onAdd({ kind: 'link', url: /^https?:\/\//.test(v) ? v : `https://${v}` })
    if (ask.kind === 'audio') onAdd({ kind: 'audio', path: v.replace(/^'|'$/g, '') })
    if (ask.kind === 'board') onBoard(v)
    setAsk(null)
    setValue('')
  }

  const tools: { label: string; glyph: string; run: () => void }[] = [
    { label: 'Note', glyph: '¶', run: () => onAdd({ kind: 'note', text: '' }, true) },
    { label: 'To-do', glyph: '☐', run: () => onAdd({ kind: 'todo', title: '', items: [] }, true) },
    { label: 'Link', glyph: '↗', run: () => setAsk({ kind: 'link', placeholder: 'Paste a link' }) },
    { label: 'Column', glyph: '▥', run: () => onAdd({ kind: 'column', title: '' }, true) },
    { label: 'Board', glyph: '▦', run: () => setAsk({ kind: 'board', placeholder: 'New board title' }) },
    { label: 'Image', glyph: '▣', run: () => picker.current?.click() },
    { label: 'Audio', glyph: '♪', run: () => setAsk({ kind: 'audio', placeholder: 'Path to a bounce (⌥⌘C in Finder)' }) },
  ]

  return (
    <div className="toolbar" onDoubleClick={(e) => e.stopPropagation()}>
      {tools.map((t) => (
        <button key={t.label} className="tool" onClick={t.run} title={t.label}>
          <span className="glyph">{t.glyph}</span>
          <span className="tool-label">{t.label}</span>
        </button>
      ))}
      <input
        ref={picker}
        type="file"
        accept="image/*"
        multiple
        hidden
        onChange={(e) => {
          onImages(Array.from(e.target.files ?? []))
          e.target.value = ''
        }}
      />
      {ask && (
        <form
          className="ask"
          onSubmit={(e) => {
            e.preventDefault()
            submit()
          }}
        >
          <input
            autoFocus
            value={value}
            placeholder={ask.placeholder}
            onChange={(e) => setValue(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && setAsk(null)}
            onBlur={() => !value && setAsk(null)}
          />
        </form>
      )}
    </div>
  )
}
