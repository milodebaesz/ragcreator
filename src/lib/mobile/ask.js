// Prompts and parsing for the "Vraag" screen.
//
// Kept apart from the component so the wording the model sees is in one place.
// Two calls per question, each in a fresh session: one turns the question into
// English search terms, one answers from the sources the search found.

/** How many sources the model gets. Its context window is a few thousand
 *  tokens, and every source also has to fit on screen as a citation. */
export const SOURCES_FOR_MODEL = 6

const SOURCE_CHARS = 700

export const KEYWORD_INSTRUCTIONS = `Je zet een klinische vraag om in Engelse zoektermen voor ESC-richtlijnen (European Society of Cardiology).
Geef 4 tot 10 zoektermen: Engelse medische termen, gangbare afkortingen en synoniemen zoals ze in richtlijnaanbevelingen staan.
Antwoord alleen met de termen, gescheiden door komma's. Geen uitleg.`

export const ANSWER_INSTRUCTIONS = `Je helpt een arts aanbevelingen uit ESC-richtlijnen te vinden.
Beantwoord de vraag uitsluitend met de genummerde bronnen die je krijgt. Gebruik geen eigen kennis.
Verwijs na elke bewering naar de bron met [1], [2], enzovoort.
Noem bij een aanbeveling de klasse en het bewijsniveau.
Beantwoorden de bronnen de vraag niet, zeg dan alleen: "Dit staat niet in de gevonden aanbevelingen."
Antwoord in het Nederlands, in hoogstens vijf korte zinnen.`

/** "statin, HMG-CoA, lipid-lowering" → ["statin", "HMG-CoA", "lipid-lowering"] */
export function parseKeywords(raw) {
  return (raw ?? '')
    .split(/[,;\n]/)
    .map(k => k.replace(/^[\s\-*•\d.)]+/, '').trim())
    .filter(k => k && k.length <= 40)
    .slice(0, 12)
}

function shorten(text, max) {
  const t = (text ?? '').replace(/\s+/g, ' ').trim()
  return t.length > max ? t.slice(0, max).replace(/\s\S*$/, '') + '…' : t
}

function sourceLine(hit, n) {
  const m = hit.chunk.metadata
  const guideline = [m.guideline || hit.project, m.year].filter(Boolean).join(' ')
  const grade = [m.class && `klasse ${m.class.replace('Class ', '')}`, m.evidence && `niveau ${m.evidence}`]
    .filter(Boolean)
    .join(', ')
  return `[${n}] ${guideline}${grade ? ` (${grade})` : ''}: ${shorten(hit.chunk.text, SOURCE_CHARS)}`
}

export function answerPrompt(question, hits) {
  const sources = hits.slice(0, SOURCES_FOR_MODEL).map((h, i) => sourceLine(h, i + 1))
  return `Vraag: ${question}\n\nBronnen:\n${sources.join('\n')}`
}

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

/**
 * The model's answer as HTML: escaped first, then only **bold**, list items
 * and [n] citations (as tappable buttons) are put back.
 */
export function renderAnswer(text, sourceCount) {
  const lines = (text ?? '').replace(/[&<>"']/g, ch => ESCAPES[ch]).split('\n')
  const out = []
  let list = false
  for (const raw of lines) {
    const line = raw.trim()
    const item = line.match(/^[-*•]\s+(.*)$/)
    if (item && !list) { out.push('<ul>'); list = true }
    if (!item && list) { out.push('</ul>'); list = false }
    if (!line) continue
    out.push(item ? `<li>${item[1]}</li>` : `<p>${line}</p>`)
  }
  if (list) out.push('</ul>')

  return out
    .join('')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    // "[1]", "[1, 3]", "[1][2]": each number its own button, and only numbers
    // that are real sources — a citation the model made up stays plain text.
    .replace(/\[(\d+(?:\s*[,–-]\s*\d+)*)\]/g, (whole, inner) => {
      const nums = inner.split(/\s*[,–-]\s*/).map(Number)
      if (!nums.every(n => n >= 1 && n <= sourceCount)) return whole
      return nums.map(n => `<button class="cite" data-source="${n}">${n}</button>`).join('')
    })
}
