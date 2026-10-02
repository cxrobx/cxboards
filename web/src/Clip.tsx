// /clip — what the "Clip to CXBoards" bookmarklet opens: the page's link (and
// any selected text) waiting to be dropped into a board's Unsorted tray.

import { useEffect, useMemo, useState } from 'react'
import { api, type Board } from './api'

const RECENT_KEY = 'cxboards.recent'

export const BOOKMARKLET = `javascript:(()=>{const s=String(getSelection()||'');const i=document.querySelector('meta[property="og:image"]');window.open('${window.location.origin}/clip?url='+encodeURIComponent(location.href)+'&title='+encodeURIComponent(document.title)+'&text='+encodeURIComponent(s.slice(0,4000))+'&img='+encodeURIComponent(i?i.content:''),'cxclip','width=460,height=600')})()`

export function ClipPage() {
  const params = new URLSearchParams(window.location.search)
  const url = params.get('url') ?? ''
  const title = params.get('title') ?? ''
  const [text, setText] = useState(params.get('text') ?? '')
  const image = params.get('img') ?? ''
  const [boards, setBoards] = useState<Board[]>([])
  const [board, setBoard] = useState('')
  const [withImage, setWithImage] = useState(false)
  const [state, setState] = useState<'idle' | 'saving' | 'saved' | string>('idle')

  useEffect(() => {
    api.boards().then((list) => {
      const usable = list.filter((b) => !b.is_template)
      let recent: string[] = []
      try {
        recent = JSON.parse(localStorage.getItem(RECENT_KEY) ?? '[]')
      } catch {
        /* no recents */
      }
      usable.sort((a, b) => (recent.indexOf(a.id) + 1 || 999) - (recent.indexOf(b.id) + 1 || 999))
      setBoards(usable)
      setBoard(usable[0]?.id ?? '')
    })
  }, [])

  const cards = useMemo(() => {
    const out: Record<string, unknown>[] = []
    if (url) out.push({ kind: 'link', url, unsorted: true })
    if (text.trim()) out.push({ kind: 'note', text: `> ${text.trim().replace(/\n/g, '\n> ')}\n\n— [${title || url}](${url})`, unsorted: true })
    if (withImage && image) out.push({ kind: 'image', image_url: image, text: title, unsorted: true })
    return out
  }, [image, text, title, url, withImage])

  const save = async () => {
    setState('saving')
    try {
      for (const card of cards) await api.addCard(board, card)
      setState('saved')
      setTimeout(() => window.close(), 900)
    } catch (e) {
      setState((e as Error).message)
    }
  }

  return (
    <div className="clip">
      <div className="brand">
        <img src="/icon.png" alt="" />
        <span>Clip to CXBoards</span>
      </div>
      <div className="clip-preview">
        <div className="card-title">{title || url || 'Nothing to clip'}</div>
        <div className="site">{url}</div>
      </div>
      <label>
        Selected text
        <textarea className="field" value={text} onChange={(e) => setText(e.target.value)} rows={5} placeholder="(none)" />
      </label>
      {image && (
        <label className="clip-check">
          <input type="checkbox" checked={withImage} onChange={(e) => setWithImage(e.target.checked)} /> Also save the page's image
        </label>
      )}
      <label>
        Into the Unsorted tray of
        <select className="field" value={board} onChange={(e) => setBoard(e.target.value)}>
          {boards.map((b) => (
            <option key={b.id} value={b.id}>
              {b.title}
            </option>
          ))}
        </select>
      </label>
      <button className="primary" disabled={!board || !cards.length || state === 'saving'} onClick={() => void save()}>
        {state === 'saved' ? 'Saved ✓' : state === 'saving' ? 'Saving…' : `Save ${cards.length} card${cards.length === 1 ? '' : 's'}`}
      </button>
      {state !== 'idle' && state !== 'saving' && state !== 'saved' && <p className="clip-error">{state}</p>}
    </div>
  )
}
