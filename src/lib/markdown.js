// Rendering the slice of markdown that guideline.md actually contains.
//
// The file is machine-produced by 1_pdf_to_markdown.py, so it uses a small and
// predictable subset: paragraphs, **bold**, _italic_, pipe tables with <br> in
// the cells, and bracketed citation runs like "[50][–][52 ]". A general-purpose
// markdown library would be a large dependency for that, and none of them
// handle the citation runs anyway.
//
// Everything is escaped first and only the constructs below are re-introduced,
// so guideline text can never inject markup into the page.

const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

function escapeHtml(text) {
  return text.replace(/[&<>"']/g, ch => ESCAPES[ch])
}

/**
 * Citation runs: "[50][–][52 ]" or "[16][,][19][,][20 ]".
 *
 * The conversion splits every number and separator into its own bracket pair.
 * Collapsing the run into one superscript is what makes body text readable —
 * left alone it is roughly a third of the characters on screen.
 */
function renderCitations(html) {
  return html.replace(/(?:\[[^\]\n]{0,12}\])+/g, run => {
    const parts = [...run.matchAll(/\[([^\]\n]{0,12})\]/g)].map(m => m[1].trim())
    // Only collapse runs that really are citations; a bracket holding words is
    // ordinary text the guideline meant to keep.
    if (!parts.length || !parts.every(p => /^(\d{1,4}|[–\-,;])$/.test(p))) return run
    return `<sup class="cite">${parts.join('')}</sup>`
  })
}

function renderInline(raw) {
  let html = escapeHtml(raw)
  html = html.replace(/&lt;br\s*\/?&gt;/gi, '<br>')
  html = renderCitations(html)
  // Bold before italic: "**_x_**" must not have its inner underscores eaten.
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  html = html.replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s.,;:)])/g, '$1<em>$2</em>')
  return html
}

function isTableRow(line) {
  return line.trimStart().startsWith('|')
}

/** A "|---|---|" separator, which carries no content of its own. */
function isTableRule(line) {
  return /^\s*\|[\s|:-]+\|\s*$/.test(line) && line.includes('-')
}

function splitCells(line) {
  const trimmed = line.trim().replace(/^\|/, '').replace(/\|$/, '')
  return trimmed.split('|').map(c => c.trim())
}

function renderTable(rows) {
  // The converter emits leading empty columns for indentation; a table where
  // every row starts empty reads better with that column dropped.
  const cells = rows.map(splitCells)
  const width = Math.max(...cells.map(r => r.length))
  const padded = cells.map(r => [...r, ...Array(width - r.length).fill('')])
  const keep = []
  for (let col = 0; col < width; col++) {
    if (padded.some(r => r[col] !== '')) keep.push(col)
  }
  if (!keep.length) return ''

  const body = padded
    .map(r => {
      const tds = keep.map(col => `<td>${renderInline(r[col])}</td>`).join('')
      return `<tr>${tds}</tr>`
    })
    .join('')
  return `<div class="md-table-wrap"><table class="md-table"><tbody>${body}</tbody></table></div>`
}

/**
 * Markdown → HTML for a single guideline section.
 * The result is trusted only because everything above escapes first.
 */
export function renderMarkdown(markdown) {
  const lines = (markdown ?? '').split('\n')
  const out = []
  let table = []
  let paragraph = []

  const flushParagraph = () => {
    if (!paragraph.length) return
    out.push(`<p>${renderInline(paragraph.join(' '))}</p>`)
    paragraph = []
  }
  const flushTable = () => {
    if (!table.length) return
    out.push(renderTable(table))
    table = []
  }

  for (const line of lines) {
    if (isTableRow(line)) {
      flushParagraph()
      if (!isTableRule(line)) table.push(line)
      continue
    }
    flushTable()

    if (!line.trim()) {
      flushParagraph()
      continue
    }
    // Headings only appear at section boundaries, which the caller strips —
    // any that survive are stray and read fine as their own paragraph.
    paragraph.push(line.replace(/^#{1,4}\s*/, '').trim())
  }
  flushParagraph()
  flushTable()

  return out.join('\n')
}

/** Plain text preview, for search snippets and list rows. */
export function stripMarkdown(markdown) {
  return (markdown ?? '')
    .replace(/\[[^\]\n]{0,12}\]/g, '')
    .replace(/[*_#|]/g, '')
    .replace(/<br\s*\/?>/gi, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}
