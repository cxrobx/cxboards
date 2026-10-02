// The left rail: one button per card kind. Links and boards ask for one line
// of input first; images, audio and files open the file picker (a picked file
// is found on disk and pointed at, the same as a Finder drop).

import { useRef, useState } from 'react'

type Ask = { kind: 'link' | 'board'; placeholder: string } | null

interface Props {
  onAdd: (spec: Record<string, unknown>, edit?: boolean) => void
  onImages: (files: File[]) => void
  onBoard: (title: string) => void
  extra?: { label: string; glyph: string; run: () => void }[]
}

export function Toolbar({ onAdd, onImages, onBoard, extra = [] }: Props) {
  const [ask, setAsk] = useState<Ask>(null)
  const [value, setValue] = useState('')
  const [accept, setAccept] = useState('image/*')
  const picker = useRef<HTMLInputElement>(null)

  const pick = (types: string) => {
    setAccept(types)
    requestAnimationFrame(() => picker.current?.click())
  }

  const submit = () => {
    const v = value.trim()
    if (!ask || !v) return
    if (ask.kind === 'link') onAdd({ kind: 'link', url: /^https?:\/\//.test(v) ? v : `https://${v}` })
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
    { label: 'Image', glyph: '▣', run: () => pick('image/*') },
    { label: 'Audio', glyph: '♪', run: () => pick('audio/*,video/*') },
    { label: 'File', glyph: '▤', run: () => pick('') },
    ...extra,
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
        accept={accept || undefined}
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
