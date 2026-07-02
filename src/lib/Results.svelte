<script>
  import { invoke } from '@tauri-apps/api/core'
  import { activeProject } from './stores.js'

  const PAGE_SIZE = 25
  const REC_CLASSES = ['Class I', 'Class IIa', 'Class IIb', 'Class III']
  const EVIDENCE_LEVELS = ['A', 'B', 'C', 'NR']

  let page  = 0
  let total = 0
  let items = []
  let loading = false
  let onlyUnapproved = false

  let editingId = null
  let draft = null
  let saving = false
  let deleting = false
  let confirmingDelete = false
  let errMsg = ''

  $: totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  $: if ($activeProject) { page = 0; load() }

  async function load() {
    if (!$activeProject) return
    loading = true
    closeEditor()
    try {
      const res = await invoke('get_chunks', {
        project: $activeProject,
        page,
        pageSize: PAGE_SIZE,
        approvedFilter: onlyUnapproved ? false : null,
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

  function setFilter(unapprovedOnly) {
    if (onlyUnapproved === unapprovedOnly) return
    onlyUnapproved = unapprovedOnly
    page = 0
    load()
  }

  async function toggleApproved(chunk, event) {
    event.stopPropagation()
    const draft = { ...chunk, metadata: { ...chunk.metadata, approved: !chunk.metadata.approved } }
    try {
      const updated = await invoke('save_chunk', { project: $activeProject, chunk: draft })
      if (onlyUnapproved && updated.metadata.approved) {
        // No longer matches the "niet geaccordeerd" filter — drop it from view.
        items = items.filter(c => c.id !== chunk.id)
        total = Math.max(0, total - 1)
      } else {
        const idx = items.findIndex(c => c.id === chunk.id)
        if (idx >= 0) items[idx] = updated
        items = items
      }
    } catch (e) {
      console.error(e)
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

  function toDraft(chunk) {
    const m = chunk.metadata ?? {}
    return {
      id: chunk.id,
      text: chunk.text ?? '',
      class: m.class ?? '',
      evidence: m.evidence ?? '',
      disease: m.disease ?? '',
      topic: m.topic ?? '',
      section: m.section ?? '',
      tableTitle: m.table_title ?? '',
      guideline: m.guideline ?? '',
      year: m.year ?? '',
      refIds: (m.ref_ids ?? []).join(', '),
      references: m.references ?? [],
      chunkType: m.chunk_type ?? 'recommendation',
      approved: m.approved ?? false,
    }
  }

  function toggleRow(chunk) {
    errMsg = ''
    confirmingDelete = false
    if (editingId === chunk.id) {
      closeEditor()
    } else {
      editingId = chunk.id
      draft = toDraft(chunk)
    }
  }

  function closeEditor() {
    editingId = null
    draft = null
    errMsg = ''
    confirmingDelete = false
  }

  function addNew() {
    errMsg = ''
    const id = `rec_manual_${Date.now()}`
    const blank = {
      id,
      text: '',
      metadata: {
        type: 'recommendation',
        class: 'Class I',
        evidence: 'A',
        disease: 'general',
        topic: 'general',
        section: '',
        table_title: '',
        guideline: '',
        year: '',
        references: [],
        ref_ids: [],
        approved: false,
      },
    }
    items = [blank, ...items]
    total += 1
    editingId = id
    draft = toDraft(blank)
  }

  function draftToChunk() {
    return {
      id: draft.id,
      text: draft.text.trim(),
      metadata: {
        type: draft.chunkType,
        class: draft.class || null,
        evidence: draft.evidence || null,
        disease: draft.disease || null,
        topic: draft.topic || null,
        section: draft.section || null,
        table_title: draft.tableTitle || null,
        guideline: draft.guideline || null,
        year: draft.year || null,
        references: draft.references,
        ref_ids: draft.refIds
          .split(',')
          .map(s => s.trim())
          .filter(s => s.length > 0 && !isNaN(Number(s)))
          .map(Number),
        approved: draft.approved,
      },
    }
  }

  async function saveDraft() {
    if (!draft) return
    saving = true
    errMsg = ''
    try {
      // save_chunk resolves reference numbers against guideline.md server-side
      // and returns the saved chunk — use that (not the local draft) so newly
      // looked-up reference text actually shows up.
      const chunk = await invoke('save_chunk', { project: $activeProject, chunk: draftToChunk() })
      if (onlyUnapproved && chunk.metadata.approved) {
        items = items.filter(c => c.id !== chunk.id)
        total = Math.max(0, total - 1)
      } else {
        const idx = items.findIndex(c => c.id === chunk.id)
        if (idx >= 0) items[idx] = chunk
        items = items
      }
      closeEditor()
    } catch (e) {
      errMsg = String(e)
    } finally {
      saving = false
    }
  }

  function requestDelete() {
    confirmingDelete = true
  }

  async function deleteDraft() {
    if (!draft) return
    deleting = true
    errMsg = ''
    try {
      await invoke('delete_chunk', { project: $activeProject, id: draft.id })
      items = items.filter(c => c.id !== draft.id)
      total = Math.max(0, total - 1)
      closeEditor()
    } catch (e) {
      errMsg = String(e)
    } finally {
      deleting = false
      confirmingDelete = false
    }
  }
</script>

<div class="results">
  <!-- Header -->
  <div class="results-header">
    <h2 class="results-title serif">Resultaten</h2>
    {#if total > 0}
      <span class="total-badge">{total} aanbevelingen</span>
    {/if}

    <div class="filter-toggle">
      <button class="filter-opt" class:active={!onlyUnapproved} on:click={() => setFilter(false)}>Alles</button>
      <button class="filter-opt" class:active={onlyUnapproved} on:click={() => setFilter(true)}>Niet geaccordeerd</button>
    </div>

    <button class="btn-add" on:click={addNew} disabled={!$activeProject}>+ Nieuwe aanbeveling</button>
  </div>

  {#if loading}
    <div class="loading-state">Laden…</div>
  {:else if items.length === 0}
    <div class="empty-state">
      <div class="empty-icon">◈</div>
      {#if onlyUnapproved}
        <p>Alles is geaccordeerd. Niets meer te reviewen op deze pagina.</p>
      {:else}
        <p>Geen chunks gevonden. Voer stap 2 uit om aanbevelingen te extraheren.</p>
      {/if}
    </div>
  {:else}
    <!-- Table -->
    <div class="table-wrap">
      <table class="chunk-table">
        <thead>
          <tr>
            <th class="col-check">Ok</th>
            <th class="col-id">#</th>
            <th class="col-class">Klasse</th>
            <th class="col-ev">Ev.</th>
            <th class="col-disease">Ziekte</th>
            <th class="col-topic">Onderwerp</th>
            <th class="col-text">Aanbeveling</th>
          </tr>
        </thead>
        <tbody>
          {#each items as chunk (chunk.id)}
            <!-- svelte-ignore a11y-click-events-have-key-events -->
            <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
            <tr
              class="chunk-row"
              class:expanded-row={editingId === chunk.id}
              class:approved-row={chunk.metadata.approved}
              on:click={() => toggleRow(chunk)}
            >
              <td class="col-check">
                <!-- svelte-ignore a11y-click-events-have-key-events -->
                <!-- svelte-ignore a11y-no-static-element-interactions -->
                <span class="approve-check" class:checked={chunk.metadata.approved}
                  on:click={(e) => toggleApproved(chunk, e)}
                  title={chunk.metadata.approved ? 'Geaccordeerd — klik om ongedaan te maken' : 'Markeer als geaccordeerd'}
                >{chunk.metadata.approved ? '✓' : ''}</span>
              </td>
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
              <td class="col-text truncate">{chunk.text || '(leeg)'}</td>
            </tr>

            {#if editingId === chunk.id && draft}
              <tr class="detail-row">
                <td colspan="7">
                  <!-- svelte-ignore a11y-click-events-have-key-events -->
                  <!-- svelte-ignore a11y-no-static-element-interactions -->
                  <div class="edit-panel" on:click|stopPropagation>
                    <label class="edit-field stretch">
                      <span class="edit-label">Tekst</span>
                      <textarea class="edit-text" rows="5" bind:value={draft.text}></textarea>
                    </label>

                    {#if draft.class === 'Class III'}
                      <p class="class3-warning">⚠ Contra-indicatie — Class III: niet aanbevolen</p>
                    {/if}

                    <div class="edit-row">
                      <label class="edit-field">
                        <span class="edit-label">Klasse</span>
                        <select bind:value={draft.class}>
                          {#each REC_CLASSES as c}<option value={c}>{c}</option>{/each}
                        </select>
                      </label>
                      <label class="edit-field">
                        <span class="edit-label">Evidence</span>
                        <select bind:value={draft.evidence}>
                          {#each EVIDENCE_LEVELS as e}<option value={e}>{e}</option>{/each}
                        </select>
                      </label>
                      <label class="edit-field">
                        <span class="edit-label">Ziekte</span>
                        <input bind:value={draft.disease} />
                      </label>
                      <label class="edit-field">
                        <span class="edit-label">Onderwerp</span>
                        <input bind:value={draft.topic} />
                      </label>
                    </div>

                    <div class="edit-row">
                      <label class="edit-field stretch">
                        <span class="edit-label">Tabel</span>
                        <input bind:value={draft.tableTitle} placeholder="—" />
                      </label>
                      <label class="edit-field stretch">
                        <span class="edit-label">Referentie-nrs (komma-gescheiden)</span>
                        <input bind:value={draft.refIds} placeholder="bijv. 12, 34, 56" />
                      </label>
                    </div>

                    <div class="edit-meta">
                      <span class="detail-label">Sectie</span>
                      <span class="detail-val">{draft.section || '—'}</span>
                    </div>

                    <label class="approve-field">
                      <input type="checkbox" bind:checked={draft.approved} />
                      Geaccordeerd
                    </label>

                    {#if draft.references?.length > 0}
                      <div class="detail-section">
                        <span class="detail-label">Opgeloste referenties ({draft.references.length})</span>
                        <ul class="ref-list">
                          {#each draft.references.slice(0,5) as ref}
                            <li><span class="ref-num">{ref.id}</span> {ref.text}</li>
                          {/each}
                          {#if draft.references.length > 5}
                            <li class="ref-more">+{draft.references.length - 5} meer</li>
                          {/if}
                        </ul>
                      </div>
                    {/if}

                    {#if errMsg}
                      <p class="err-msg">{errMsg}</p>
                    {/if}

                    <div class="edit-actions">
                      {#if confirmingDelete}
                        <span class="confirm-text">Definitief verwijderen?</span>
                        <button class="btn-ghost" on:click={() => confirmingDelete = false}>Nee</button>
                        <button class="btn-danger" on:click={deleteDraft} disabled={deleting}>
                          {deleting ? 'Verwijderen…' : 'Ja, verwijderen'}
                        </button>
                      {:else}
                        <button class="btn-ghost" on:click={closeEditor}>Annuleren</button>
                        <button class="btn-danger" on:click={requestDelete}>Verwijderen</button>
                        <button class="btn-save" on:click={saveDraft} disabled={saving}>
                          {saving ? 'Opslaan…' : 'Opslaan'}
                        </button>
                      {/if}
                    </div>
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
    padding: 2px 9px;
    background: var(--accent-dim);
    color: var(--accent-h);
    border-radius: 3px;
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
  }
  .btn-add {
    margin-left: auto;
    padding: 7px 14px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    color: var(--text-2);
    font-size: 12.5px;
    font-weight: 600;
    transition: background .12s, color .12s, border-color .12s;
  }
  .btn-add:hover:not(:disabled) { background: var(--accent-dim); color: var(--accent-h); border-color: var(--accent); }
  .btn-add:disabled { opacity: .4; cursor: not-allowed; }

  .filter-toggle {
    display: flex;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
  }
  .filter-opt {
    padding: 6px 12px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-2);
    transition: background .12s, color .12s;
  }
  .filter-opt + .filter-opt { border-left: 1px solid var(--border); }
  .filter-opt:hover  { background: var(--bg-hover); }
  .filter-opt.active { background: var(--accent); color: #fff; }

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
  .chunk-row.approved-row { opacity: .55; }
  .chunk-row.approved-row:hover,
  .chunk-row.approved-row.expanded-row { opacity: 1; }

  .approve-check {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 20px; height: 20px;
    margin: 0 auto;
    border-radius: 4px;
    border: 1px solid var(--border);
    color: #fff;
    font-size: 13px;
    font-weight: 700;
    line-height: 1;
    cursor: pointer;
    transition: background .12s, border-color .12s;
  }
  .approve-check:hover   { border-color: var(--success); }
  .approve-check.checked { background: var(--success); border-color: var(--success); }

  td {
    padding: 9px 12px;
    vertical-align: middle;
  }

  .col-check   { width: 40px; text-align: center; }
  .col-id      { width: 80px; }
  .col-class   { width: 90px; }
  .col-ev      { width: 60px; }
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
    padding: 3px 8px;
    border-radius: 4px;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .02em;
    font-family: var(--mono);
  }
  .class1  { background: #3f7a56; color: #f0faf4; }
  .class2a { background: #a67f2e; color: #fffaf0; }
  .class2b { background: #b5732a; color: #fff6ee; }
  .class3  { background: #a8453a; color: #fff1ef; }
  .neutral { background: var(--bg-hover);       color: var(--text-1); }
  .ev-a    { background: var(--accent);         color: #fff; }
  .ev-b    { background: #3d6a80;               color: #eaf7fc; }
  .ev-c    { background: #5c5566;               color: #f2eff5; }
  .ev-nr   { background: var(--bg-hover); color: var(--text-2); }

  /* Detail / edit row */
  .detail-row td  { padding: 0; }
  .edit-panel {
    padding: 18px 20px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
    border-left: 2px solid var(--accent);
    cursor: default;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .edit-row { display: flex; gap: 12px; flex-wrap: wrap; }
  .edit-field { display: flex; flex-direction: column; gap: 5px; flex: 1; min-width: 120px; }
  .edit-field.stretch { flex: 2; min-width: 220px; }
  .edit-label {
    font-size: 11px; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; color: var(--text-3);
  }
  .edit-text {
    width: 100%; resize: vertical;
    font-family: inherit; font-size: 13px; line-height: 1.6;
    background: var(--bg-card);
  }
  .edit-field input, .edit-field select {
    width: 100%;
    background: var(--bg-card);
  }

  .class3-warning {
    font-size: 12px; font-weight: 600; color: #d6897b;
    background: var(--error-dim); border-radius: var(--radius);
    padding: 6px 10px;
  }

  .edit-meta { display: flex; align-items: baseline; gap: 8px; }

  .approve-field {
    display: flex; align-items: center; gap: 8px;
    font-size: 13px; font-weight: 600; color: var(--text-1);
    cursor: pointer;
  }
  .approve-field input { width: 16px; height: 16px; accent-color: var(--success); cursor: pointer; }

  .detail-section { display: flex; flex-direction: column; gap: 4px; }
  .detail-label   { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); }
  .detail-val     { font-size: 13px; color: var(--text-2); }

  .ref-list { list-style: none; display: flex; flex-direction: column; gap: 4px; }
  .ref-list li { font-size: 12px; color: var(--text-2); }
  .ref-num {
    display: inline-block;
    min-width: 22px;
    padding: 0 4px;
    margin-right: 4px;
    border-radius: 3px;
    background: var(--bg-hover);
    color: var(--text-3);
    font-family: var(--mono);
    font-size: 11px;
    text-align: center;
  }
  .ref-more { color: var(--text-3); font-style: italic; }

  .err-msg { font-size: 12px; color: #d6897b; }

  .edit-actions {
    display: flex; align-items: center; justify-content: flex-end; gap: 10px; margin-top: 4px;
  }
  .confirm-text { font-size: 12.5px; color: var(--text-2); margin-right: 2px; }
  .btn-ghost {
    padding: 7px 14px;
    border-radius: var(--radius);
    color: var(--text-2);
    transition: background .12s;
  }
  .btn-ghost:hover { background: var(--bg-hover); color: var(--text-1); }
  .btn-danger {
    padding: 7px 14px;
    border-radius: var(--radius);
    border: 1px solid var(--error);
    color: #d6897b;
    font-weight: 600;
    transition: background .12s;
  }
  .btn-danger:hover:not(:disabled) { background: var(--error-dim); }
  .btn-danger:disabled { opacity: .5; cursor: not-allowed; }
  .btn-save {
    padding: 7px 18px;
    border-radius: var(--radius);
    background: var(--accent);
    color: #fff;
    font-weight: 600;
    transition: background .12s, opacity .12s;
  }
  .btn-save:hover:not(:disabled) { background: var(--accent-h); }
  .btn-save:disabled { opacity: .5; cursor: not-allowed; }

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
