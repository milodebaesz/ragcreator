// Parsing of guideline reference strings into something clickable.
//
// The reference text comes out of the PDF→markdown conversion in Vancouver
// style, e.g.
//
//   Velazquez EJ, Lee KL, Jones RH, et al. Coronary-artery bypass surgery in
//   patients with ischemic cardiomyopathy. N Engl J Med 2016; 374 :1511–20.
//   https://doi.org/10.1056/NEJMoa1602001
//
// The conversion damages DOIs — it inserts spaces ("https://doi. org/10.1056/
// NEJMoa1916370") and, where the PDF broke a line mid-DOI, it silently drops a
// hyphen ("10.1007/s00392-02302362-6" for …/s00392-023-02362-6). A DOI is
// therefore treated as a bonus link, never as the only way out: the title
// search is what reliably lands on the right PubMed record.

const YEAR_VOLUME_RE = /\b((?:19|20)\d{2})\s*;\s*(\d+)?/
const PMID_RE = /\bPMID:?\s*(\d{4,9})\b/i

/** Whitespace the PDF sprinkled into URLs and page ranges. */
function compact(text) {
  return text.replace(/\s+/g, '')
}

/** A DOI that survived conversion intact enough to be worth resolving. */
function looksResolvable(doi) {
  // A dropped hyphen leaves a run of digits far longer than any real suffix
  // segment; those DOIs 404 on doi.org, so they are not offered as a link.
  if (/\d{9,}/.test(doi)) return false
  return /^10\.\d{4,9}\/\S{3,}$/.test(doi)
}

export function extractDoi(text) {
  const idx = text.search(/10\.\d{4}/)
  if (idx === -1) return null
  // Everything from the "10." onwards belongs to the DOI: it is always the
  // last thing on a reference line.
  const doi = compact(text.slice(idx)).replace(/[.,;)\]]+$/, '')
  return looksResolvable(doi) ? doi : null
}

/**
 * Split a Vancouver-style reference into its parts.
 * Every field is best-effort — callers must cope with nulls.
 */
export function parseReference(text) {
  const raw = (text ?? '').replace(/\s+/g, ' ').trim()
  const doi = extractDoi(raw)
  const pmidMatch = raw.match(PMID_RE)

  // Drop the trailing URL/DOI so it cannot be mistaken for the title.
  let body = raw.replace(/\s*https?:\s*\/\/.*$/i, '').trim()

  // Authors: the leading run of "Surname AB" entries, which the style always
  // closes with a period. "et al" is the common case; a short author list ends
  // with the last surname instead.
  let authors = null
  let rest = body
  const etAl = body.match(/^(.{0,400}?\bet al)\.\s+/)
  if (etAl) {
    authors = etAl[1]
    rest = body.slice(etAl[0].length)
  } else {
    // One author: optional lowercase particles ("van de Ven"), a surname,
    // initials, and an optional generational suffix ("Hood WB Jr").
    const AUTHOR = String.raw`(?:[a-z]{1,4}\s+){0,3}[A-Z][\p{L}'’-]+(?:\s+[A-Z]{1,3})?(?:\s+(?:Jr|Sr|2nd|3rd|II|III|IV))?`
    const listed = body.match(
      new RegExp(String.raw`^(${AUTHOR}(?:\s*,\s*${AUTHOR})*(?:\s*;\s*[^.]{3,80})?)\.\s+`, 'u'),
    )
    if (listed) {
      authors = listed[1]
      rest = body.slice(listed[0].length)
    }
  }

  // Journal segment: the one carrying "Year;Volume". The title is everything
  // before the sentence break that precedes it.
  let title = null
  let journal = null
  let year = null
  let volume = null
  let pages = null

  const yv = rest.match(YEAR_VOLUME_RE)
  if (yv) {
    year = yv[1]
    volume = yv[2] ?? null
    const head = rest.slice(0, yv.index)
    const cut = head.lastIndexOf('. ')
    if (cut > 0) {
      title = head.slice(0, cut).trim()
      journal = head.slice(cut + 1).trim()
    } else {
      title = head.trim()
    }
    const pageMatch = rest.slice(yv.index).match(/:\s*([\dA-Za-z–\-–]+)/)
    if (pageMatch) pages = compact(pageMatch[1])
  } else {
    // No year/volume (a website, a report) — take the first sentence as title.
    const cut = rest.indexOf('. ')
    title = (cut > 0 ? rest.slice(0, cut) : rest).trim()
  }

  if (title) title = title.replace(/^[.\s]+|[.\s]+$/g, '')
  if (!title) title = null

  return {
    raw,
    authors,
    title,
    journal: journal || null,
    year,
    volume,
    pages,
    doi,
    pmid: pmidMatch ? pmidMatch[1] : null,
  }
}

/**
 * PubMed link for a reference.
 *
 * A PMID goes straight to the record. Otherwise a title search is used, which
 * PubMed resolves to the single matching article; the DOI is deliberately not
 * the first choice because conversion damage makes it unreliable.
 */
export function pubmedUrl(ref) {
  if (ref.pmid) return `https://pubmed.ncbi.nlm.nih.gov/${ref.pmid}/`

  const base = 'https://pubmed.ncbi.nlm.nih.gov/?term='
  if (ref.title && ref.title.length > 15) {
    return base + encodeURIComponent(`${ref.title}[Title]`)
  }
  if (ref.doi) return base + encodeURIComponent(ref.doi)
  return base + encodeURIComponent(ref.raw.slice(0, 300))
}

export function doiUrl(ref) {
  return ref.doi ? `https://doi.org/${ref.doi}` : null
}

export function scholarUrl(ref) {
  // Scholar tolerates the damaged citation far better than a DOI resolver, so
  // the whole string is handed over as the query.
  const q = ref.title || ref.raw
  return 'https://scholar.google.com/scholar?q=' + encodeURIComponent(q.slice(0, 300))
}

/** Short label for the reference list, e.g. "Velazquez EJ, et al. — N Engl J Med 2016". */
export function shortCitation(ref) {
  const bits = []
  if (ref.authors) bits.push(ref.authors.length > 40 ? ref.authors.slice(0, 40) + '…' : ref.authors)
  const tail = [ref.journal, ref.year].filter(Boolean).join(' ')
  if (tail) bits.push(tail)
  return bits.join(' · ')
}
