// The open board's theme, worn by the whole app. The server computes the palette
// (src/cxboards/themes.py); this writes it onto the page as the CSS tokens every
// style is built on, and tells CXBoards.app so the window (traffic lights, native
// sheets and menus, its background) follows. Vault (no palette) restores the app's
// own look, which follows the Mac's light/dark setting.

export interface Palette {
  scheme: 'light' | 'dark'
  canvas: string
  ground: string
  card: string
  fill: string
  line: string
  lineInk: string
  ink: string
  muted: string
  accent: string
  onAccent: string
  glow: string
  shadow: string
  font: string
  fontDisplay: string
  fontWeight: string
  radius: string
  radiusLg: string
  accent2?: string
  fontsHref?: string
  displayStyle?: string
  displayWeight?: string
  grain?: string
  backdrop?: string
  backdropDim?: string
  backdropBlur?: string
  backdropScrim?: string
}

const TOKENS: [keyof Palette, string[]][] = [
  ['canvas', ['--canvas']],
  ['ground', ['--ground']],
  ['card', ['--card']],
  ['fill', ['--fill']],
  ['line', ['--line']],
  ['lineInk', ['--line-ink']],
  ['ink', ['--ink']],
  ['muted', ['--muted']],
  ['accent', ['--amber', '--clay']],
  ['onAccent', ['--on-accent']],
  ['glow', ['--glow']],
  ['shadow', ['--shadow']],
  ['font', ['--font']],
  ['fontDisplay', ['--font-display']],
  ['fontWeight', ['--font-weight']],
  ['accent2', ['--accent-2']],
  ['displayStyle', ['--font-display-style']],
  ['displayWeight', ['--font-display-weight']],
  ['backdropDim', ['--backdrop-dim']],
  ['backdropBlur', ['--backdrop-blur']],
  ['backdropScrim', ['--backdrop-scrim']],
]

/** The theme's Google fonts, served from CXBoards' own cache (src/cxboards/fonts.py). */
function loadFonts(href: string | undefined) {
  let link = document.getElementById('theme-fonts') as HTMLLinkElement | null
  if (!href) {
    link?.remove()
    return
  }
  if (!link) {
    link = document.createElement('link')
    link.id = 'theme-fonts'
    link.rel = 'stylesheet'
    document.head.appendChild(link)
  }
  if (link.getAttribute('href') !== href) link.href = href
}

type Bridge = { postMessage: (body: unknown) => void }
const native: Bridge | undefined = (window as unknown as { webkit?: { messageHandlers?: { cxTheme?: Bridge } } }).webkit
  ?.messageHandlers?.cxTheme

let worn: string | null = null

export function applyPalette(palette: Palette | null | undefined) {
  const key = palette ? JSON.stringify(palette) : null
  if (key === worn) return
  worn = key
  const root = document.documentElement
  for (const [field, vars] of TOKENS) {
    for (const v of vars) {
      const value = palette?.[field]
      if (value) root.style.setProperty(v, value)
      else root.style.removeProperty(v)
    }
  }
  loadFonts(palette?.fontsHref)
  // The backdrop (an uploaded image under a scrim) and the grain are drawn by styles.css from these.
  if (palette?.backdrop) {
    root.style.setProperty('--backdrop-image', `url("${palette.backdrop}")`)
    root.dataset.backdrop = ''
  } else {
    root.style.removeProperty('--backdrop-image')
    delete root.dataset.backdrop
  }
  if (palette?.grain && palette.grain !== 'none') root.dataset.grain = palette.grain
  else delete root.dataset.grain
  if (palette?.displayWeight) root.dataset.displayFont = ''
  else delete root.dataset.displayFont
  root.style.colorScheme = palette ? palette.scheme : ''
  if (palette) root.dataset.scheme = palette.scheme
  else delete root.dataset.scheme
  // Square themes are square everywhere (chrisx.art: "square EVERYTHING").
  if (palette?.radius === '0px') root.dataset.corners = 'square'
  else delete root.dataset.corners
  native?.postMessage(palette ? { appearance: palette.scheme, ground: palette.canvas } : { appearance: null, ground: null })
}
