<script>
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import { activeProject } from './stores.js'

  const PAGE_SIZE = 25

  let page  = 0
  let total = 0
  let items = []
  let loading = false
  let expanded = null

  $: totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  $: if ($activeProject) { page = 0; load() }

  async function load() {
    if (!$activeProject) return
    loading = true
    expanded = null
    try {
      const res = await invoke('get_chunks', {
        project: $activeProject,
        page,
        pageSize: PAGE_SIZE,
      })
      items = res.items
      total = res.total
    } catch (e) {
      console.error(e)
      items = []
    } finally {
      loading = false
    }
  }

  function prevPage() { if (page > 0) { page--; load() } }
  function nextPage() { if (page < totalPages - 1) { page++; load() } }

  function classColor(cls) {
    if (!cls) return 'neutral'
    if (cls.includes('I') && !cls.includes('II')) return 'class1'
    if (cls.includes('IIa')) return 'class2a'
    if (cls.includes('IIb')) return 'class2b'
    if (cls.includes('III')) return 'class3'
    return 'neutral'
  }

  function evidenceColor(ev) {
    if (ev === 'A') return 'ev-a'
    if (ev === 'B') return 'ev-b'
    if (ev === 'C') return 'ev-c'
    return 'ev-nr'
  }
</script>

<div class="results">
  <!-- Header -->
  <div class="results-header">
    <h2 class="results-title">Resultaten</h2>
    {#if total > 0}
      <span class="total-badge">{total} aanbevelingen</span>
    {/if}
  </div>

  {#if loading}
    <div class="loading-state">Laden…</div>
  {:else if items.length === 0}
    <div class="empty-state">
      <div class="empty-icon">◈</div>
      <p>Geen chunks gevonden. Voer stap 2 uit om aanbevelingen te extraheren.</p>
    </div>
  {:else}
    <!-- Table -->
    <div class="table-wrap">
      <table class="chunk-table">
        <thead>
          <tr>
            <th class="col-id">#</th>
            <th class="col-class">Klasse</th>
            <th class="col-ev">Ev.</th>
            <th class="col-disease">Ziekte</th>
            <th class="col-topic">Onderwerp</th>
            <th class="col-text">Aanbeveling</th>
          </tr>
        </thead>
        <tbody>
          {#each items as chunk}
            <tr
              class="chunk-row"
              class:expanded-row={expanded === chunk.id}
              on:click={() => expanded = expanded === chunk.id ? null : chunk.id}
            >
              <td class="col-id mono">{chunk.id}</td>
              <td class="col-class">
                {#if chunk.metadata.class}
                  <span class="badge {classColor(chunk.metadata.class)}">
                    {chunk.metadata.class.replace('Class ', '')}
                  </span>
                {/if}
              </td>
              <td class="col-ev">
                {#if chunk.metadata.evidence}
                  <span class="badge {evidenceColor(chunk.metadata.evidence)}">
                    {chunk.metadata.evidence}
                  </span>
                {/if}
              </td>
              <td class="col-disease tag">{chunk.metadata.disease ?? '—'}</td>
              <td class="col-topic tag">{chunk.metadata.topic ?? '—'}</td>
              <td class="col-text truncate">{chunk.text}</td>
            </tr>

            {#if expanded === chunk.id}
              <tr class="detail-row">
                <td colspan="6">
                  <div class="detail-panel">
                    <div class="detail-section">
                      <span class="detail-label">Sectie</span>
                      <span class="detail-val">{chunk.metadata.section ?? '—'}</span>
                    </div>
                    <div class="detail-section">
                      <span class="detail-label">Tekst</span>
                      <p class="detail-text">{chunk.text}</p>
                    </div>
                    {#if chunk.metadata.references?.length > 0}
                      <div class="detail-section">
                        <span class="detail-label">Referenties ({chunk.metadata.references.length})</span>
                        <ul class="ref-list">
                          {#each chunk.metadata.references.slice(0,5) as ref}
                            <li>{ref}</li>
                          {/each}
                          {#if chunk.metadata.references.length > 5}
                            <li class="ref-more">+{chunk.metadata.references.length - 5} meer</li>
                          {/if}
                        </ul>
                      </div>
                    {/if}
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div class="pagination">
      <button class="pg-btn" on:click={prevPage} disabled={page === 0}>← Vorige</button>
      <span class="pg-info">Pagina {page + 1} van {totalPages}</span>
      <button class="pg-btn" on:click={nextPage} disabled={page >= totalPages - 1}>Volgende →</button>
    </div>
  {/if}
</div>

<style>
  .results {
    padding: 24px 28px;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 16px;
    overflow: hidden;
  }

  .results-header {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-shrink: 0;
  }
  .results-title { font-size: 20px; font-weight: 600; }
  .total-badge {
    padding: 2px 10px;
    background: var(--accent-dim);
    color: var(--accent-h);
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
  }

  .loading-state, .empty-state {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    color: var(--text-3);
    font-size: 14px;
  }
  .empty-icon { font-size: 40px; opacity: .3; }

  /* Table */
  .table-wrap {
    flex: 1;
    overflow: auto;
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
  }

  .chunk-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }

  thead th {
    position: sticky;
    top: 0;
    background: var(--bg-card);
    padding: 10px 12px;
    text-align: left;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    color: var(--text-3);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }

  .chunk-row {
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    transition: background .1s;
  }
  .chunk-row:hover        { background: var(--bg-hover); }
  .chunk-row.expanded-row { background: var(--accent-dim); }

  td {
    padding: 9px 12px;
    vertical-align: middle;
  }

  .col-id      { width: 80px; }
  .col-class   { width: 80px; }
  .col-ev      { width: 50px; }
  .col-disease { width: 80px; }
  .col-topic   { width: 110px; }
  .col-text    { }

  .mono    { font-family: var(--mono); font-size: 11px; color: var(--text-3); }
  .truncate {
    max-width: 420px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: var(--text-2);
  }
  .tag { font-size: 12px; color: var(--text-3); }

  /* Badges */
  .badge {
    display: inline-block;
    padding: 2px 7px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 700;
    font-family: var(--mono);
  }
  .class1  { background: rgba(34,197,94,.15);  color: #4ade80; }
  .class2a { background: rgba(250,204,21,.12); color: #fbbf24; }
  .class2b { background: rgba(245,158,11,.12); color: #f59e0b; }
  .class3  { background: rgba(239,68,68,.15);  color: #f87171; }
  .neutral { background: var(--bg-hover);       color: var(--text-2); }
  .ev-a    { background: rgba(99,102,241,.2);  color: var(--accent-h); }
  .ev-b    { background: rgba(14,165,233,.15); color: #38bdf8; }
  .ev-c    { background: rgba(148,163,184,.12); color: #94a3b8; }
  .ev-nr   { background: var(--bg-hover); color: var(--text-3); }

  /* Detail row */
  .detail-row td  { padding: 0; }
  .detail-panel   {
    padding: 16px 20px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .detail-section { display: flex; flex-direction: column; gap: 4px; }
  .detail-label   { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); }
  .detail-val     { font-size: 13px; color: var(--text-2); }
  .detail-text    { font-size: 13px; color: var(--text-1); line-height: 1.6; white-space: pre-wrap; }

  .ref-list { list-style: none; display: flex; flex-direction: column; gap: 3px; }
  .ref-list li    { font-size: 12px; color: var(--text-2); padding-left: 10px; position: relative; }
  .ref-list li::before { content: '—'; position: absolute; left: 0; color: var(--text-3); }
  .ref-more { color: var(--text-3); font-style: italic; }

  /* Pagination */
  .pagination {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    flex-shrink: 0;
    padding: 4px 0;
  }
  .pg-btn {
    padding: 6px 14px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    font-size: 12px;
    color: var(--text-2);
    transition: background .12s;
  }
  .pg-btn:hover    { background: var(--bg-hover); color: var(--text-1); }
  .pg-btn:disabled { opacity: .3; cursor: not-allowed; }
  .pg-info { font-size: 12px; color: var(--text-3); }
</style>
