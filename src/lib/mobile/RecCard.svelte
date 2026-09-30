<script>
  // One recommendation, collapsed to its text and badges until tapped.
  //
  // Shared by the Aanbevelingen list and the Zoeken results so a recommendation
  // looks and behaves the same wherever it turns up.
  import { invoke } from '@tauri-apps/api/core'
  import { parseReference, pubmedUrl, doiUrl, scholarUrl, shortCitation } from '../references.js'
  import { openPdf } from './pdf.js'

  export let chunk
  export let project
  /** Highlighted in the body text when the card comes from a search. */
  export let query = ''

  let open = false
  let pdf = null
  let pdfChecked = false
  let linkErr = ''

  $: refs = (chunk.metadata.references ?? []).map(r => ({ id: r.id, ...parseReference(r.text) }))

  async function toggle() {
    open = !open
    // The PDF lookup only reads a cache file, but there is no reason to do it
    // for the dozens of cards that are never opened.
    if (open && !pdfChecked) {
      pdfChecked = true
      try {
        pdf = await invoke('get_pdf_location', { project, chunkId: chunk.id })
      } catch (e) {
        pdf = null
      }
    }
  }

  async function openUrl(url) {
    linkErr = ''
    try {
      await invoke('open_external', { url })
    } catch (e) {
      linkErr = String(e)
    }
  }

  function classColor(cls) {
    if (!cls) return 'neutral'
    if (cls.includes('IIa')) return 'class2a'
    if (cls.includes('IIb')) return 'class2b'
    if (cls.includes('III')) return 'class3'
    if (cls.includes('I')) return 'class1'
    return 'neutral'
  }

  function evidenceColor(ev) {
    if (ev === 'A') return 'ev-a'
    if (ev === 'B1' || ev === 'B2' || ev === 'B') return 'ev-b'
    if (ev === 'C') return 'ev-c'
    return 'ev-nr'
  }

  const ESCAPES = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }

  /** Escapes first, so recommendation text can never inject markup. */
  function highlight(text, q) {
    const safe = (text ?? '').replace(/[&<>"']/g, ch => ESCAPES[ch])
    const needle = q.trim()
    if (!needle) return safe
    const escaped = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
    return safe.replace(new RegExp(`(${escaped})`, 'gi'), '<mark>$1</mark>')
  }

  function shortTable(title) {
    if (!title) return ''
    const idx = title.indexOf('—')
    return idx === -1 ? title : title.slice(0, idx).trim()
  }
</script>

<article class="card" class:open>
  <!-- A <button> may only hold phrasing content, and this header holds a
       badge row and a paragraph. WebKit renders such a button empty, so the
       header is a div carrying the button role and its keyboard behaviour. -->
  <div
    class="card-head"
    role="button"
    tabindex="0"
    aria-expanded={open}
    on:click={toggle}
    on:keydown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggle() } }}
  >
    <div class="badges">
      {#if chunk.metadata.class}
        <span class="badge {classColor(chunk.metadata.class)}">
          {chunk.metadata.class.replace('Class ', '')}
        </span>
      {/if}
      {#if chunk.metadata.evidence}
        <span class="badge {evidenceColor(chunk.metadata.evidence)}">{chunk.metadata.evidence}</span>
      {/if}
      {#if chunk.metadata.approved}
        <span class="badge approved">✓</span>
      {/if}
      <span class="spacer"></span>
      <span class="chev" class:open>›</span>
    </div>
    <p class="text">{@html highlight(chunk.text, query)}</p>
  </div>

  {#if open}
    <div class="detail">
      {#if chunk.metadata.section}
        <div class="meta-row"><span class="meta-key">Sectie</span><span>{chunk.metadata.section}</span></div>
      {/if}
      {#if chunk.metadata.table_title}
        <div class="meta-row"><span class="meta-key">Tabel</span><span>{shortTable(chunk.metadata.table_title)}</span></div>
      {/if}
      {#if chunk.metadata.disease || chunk.metadata.topic}
        <div class="meta-row">
          <span class="meta-key">Onderwerp</span>
          <span>{[chunk.metadata.disease, chunk.metadata.topic].filter(Boolean).join(' · ')}</span>
        </div>
      {/if}

      {#if pdf}
        <div class="pdf-row">
          <div class="pdf-info">
            <span class="pdf-name">{pdf.file_name}</span>
            {#if pdf.page}
              <span class="pdf-page">pagina {pdf.page}</span>
            {:else}
              <span class="pdf-page dim">pagina onbekend</span>
            {/if}
          </div>
          <button class="pdf-btn" on:click={() => openPdf(project, pdf.page)}>
            {pdf.page ? `Open op p. ${pdf.page}` : 'Open PDF'}
          </button>
        </div>
      {/if}

      {#if refs.length}
        <h4 class="refs-title">Referenties ({refs.length})</h4>
        <ul class="refs">
          {#each refs as ref}
            <li class="ref">
              <div class="ref-head">
                {#if ref.id}<span class="ref-num">{ref.id}</span>{/if}
                <span class="ref-title">{ref.title ?? ref.raw.slice(0, 120)}</span>
              </div>
              {#if shortCitation(ref)}
                <div class="ref-cite">{shortCitation(ref)}</div>
              {/if}
              <div class="ref-links">
                <button on:click={() => openUrl(pubmedUrl(ref))}>PubMed</button>
                {#if doiUrl(ref)}
                  <button on:click={() => openUrl(doiUrl(ref))}>Volledige tekst</button>
                {/if}
                <button on:click={() => openUrl(scholarUrl(ref))}>Scholar</button>
              </div>
            </li>
          {/each}
        </ul>
      {:else}
        <p class="no-refs">Geen referenties bij deze aanbeveling.</p>
      {/if}

      {#if linkErr}<p class="link-err">{linkErr}</p>{/if}
    </div>
  {/if}
</article>

<style>
  .card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    /* The list is a column flex container, and `overflow: hidden` sets a flex
       item's automatic minimum size to zero — without this the cards are
       squashed to a few pixels as soon as the list overflows. */
    flex-shrink: 0;
  }
  .card.open { border-color: var(--accent); }

  .card-head {
    display: block;
    width: 100%;
    text-align: left;
    padding: 14px 16px;
    /* Comfortably above the 44px Apple touch target minimum. */
    min-height: 56px;
  }

  .badges { display: flex; align-items: center; gap: 6px; margin-bottom: 8px; }
  .spacer { flex: 1; }

  .badge {
    font-size: 11.5px;
    font-weight: 700;
    letter-spacing: .03em;
    padding: 3px 8px;
    border-radius: 4px;
  }
  .class1  { background: rgba(92,157,118,.20); color: #7fc39a; }
  .class2a { background: rgba(201,144,63,.20); color: #ddab63; }
  .class2b { background: rgba(201,144,63,.12); color: #b4913f; }
  .class3  { background: rgba(200,96,78,.20);  color: #d6897b; }
  .neutral { background: var(--bg-hover); color: var(--text-2); }
  .ev-a  { background: rgba(92,157,118,.16); color: #7fc39a; }
  .ev-b  { background: rgba(201,144,63,.16); color: #ddab63; }
  .ev-c  { background: var(--bg-hover); color: var(--text-2); }
  .ev-nr { background: var(--bg-hover); color: var(--text-3); }
  .approved { background: rgba(92,157,118,.20); color: #7fc39a; }

  .chev {
    color: var(--text-3);
    font-size: 20px;
    line-height: 1;
    transition: transform .18s;
  }
  .chev.open { transform: rotate(90deg); color: var(--accent-h); }

  .text {
    font-size: 15.5px;
    line-height: 1.5;
    color: var(--text-1);
  }
  .text :global(mark) {
    background: var(--accent-dim);
    color: var(--accent-h);
    border-radius: 2px;
    padding: 0 1px;
  }

  .detail {
    padding: 0 16px 16px;
    border-top: 1px solid var(--border);
    padding-top: 14px;
  }

  .meta-row {
    display: flex;
    gap: 10px;
    font-size: 13.5px;
    color: var(--text-2);
    padding: 4px 0;
  }
  .meta-key {
    flex: 0 0 76px;
    color: var(--text-3);
    text-transform: uppercase;
    font-size: 11px;
    letter-spacing: .05em;
    padding-top: 2px;
  }

  .pdf-row {
    display: flex;
    align-items: center;
    gap: 10px;
    margin: 12px 0;
    padding: 10px 12px;
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .pdf-info { flex: 1; min-width: 0; }
  .pdf-name {
    display: block;
    font-size: 13px;
    color: var(--text-1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .pdf-page { font-size: 12px; color: var(--accent-h); }
  .pdf-page.dim { color: var(--text-3); }
  .pdf-btn {
    flex-shrink: 0;
    background: var(--accent-dim);
    color: var(--accent-h);
    border-radius: var(--radius);
    padding: 9px 12px;
    font-size: 13px;
    font-weight: 600;
    min-height: 40px;
  }

  .refs-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--text-3);
    margin: 14px 0 8px;
  }
  .refs { list-style: none; display: flex; flex-direction: column; gap: 12px; }
  .ref-head { display: flex; gap: 8px; }
  .ref-num {
    flex-shrink: 0;
    font-size: 11px;
    color: var(--accent-h);
    background: var(--accent-dim);
    border-radius: 3px;
    padding: 1px 6px;
    height: fit-content;
    margin-top: 2px;
  }
  .ref-title { font-size: 13.5px; line-height: 1.45; color: var(--text-1); }
  .ref-cite { font-size: 12px; color: var(--text-3); margin: 3px 0 0 30px; }
  .ref-links { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 0 30px; }
  .ref-links button {
    font-size: 12.5px;
    color: var(--text-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 8px 12px;
    min-height: 38px;
  }
  .ref-links button:active { background: var(--bg-hover); color: var(--accent-h); }

  .no-refs { font-size: 13px; color: var(--text-3); margin-top: 12px; }
  .link-err { font-size: 12.5px; color: #d6897b; margin-top: 10px; }
</style>
