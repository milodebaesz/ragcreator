<script>
  import { tick } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import { activeProject } from './stores.js'
  import ReferenceList from './ReferenceList.svelte'
  import PdfViewer from './PdfViewer.svelte'

  const ALL = 100000
  const REC_CLASSES = ['Class I', 'Class IIa', 'Class IIb', 'Class III']
  // ESC grades therapy/prevention as A/B1/B2/C since 2026, diagnostics as A/B/C.
  const EVIDENCE_LEVELS = ['A', 'B1', 'B2', 'B', 'C', 'NR']
  const NO_TABLE_KEY = '__none__'

  let total = 0
  let items = []
  let loading = false
  let onlyUnapproved = false
  let loadErr = ''

  let editingId = null
  let draft = null
  let saving = false
  let deleting = false
  let confirmingDelete = false
  let errMsg = ''

  let collapsedKeys = new Set()

  // Chunk shown in the PDF source viewer, null when the viewer is closed.
  let pdfChunk = null

  let exportOpen = false
  let exporting = false
  let exportMsg = ''

  $: if ($activeProject) load()

  $: groups = groupItems(items)

  function splitTitle(title) {
    const idx = title.indexOf('—')
    if (idx === -1) return { short: title, rest: '' }
    return { short: title.slice(0, idx).trim(), rest: title.slice(idx + 1).trim() }
  }

  function extractTableNum(title) {
    const m = title.match(/Table\s+(\d+)/i)
    return m ? Number(m[1]) : null
  }

  function groupKey(chunk) {
    return (chunk.metadata.table_title || '').trim() || NO_TABLE_KEY
  }

  function groupItems(list) {
    const map = new Map()
    for (const c of list) {
      const key = groupKey(c)
      if (!map.has(key)) map.set(key, [])
      map.get(key).push(c)
    }
    const result = [...map.entries()].map(([key, chunks]) => {
      const title = key === NO_TABLE_KEY ? 'Overig / geen tabel' : key
      const { short, rest } = splitTitle(title)
      return {
        key,
        short,
        rest,
        chunks,
        approvedCount: chunks.filter(c => c.metadata.approved).length,
        num: key === NO_TABLE_KEY ? null : extractTableNum(title),
      }
    })
    result.sort((a, b) => {
      if (a.key === NO_TABLE_KEY) return 1
      if (b.key === NO_TABLE_KEY) return -1
      if (a.num != null && b.num != null) return a.num - b.num
      if (a.num != null) return -1
      if (b.num != null) return 1
      return a.short.localeCompare(b.short)
    })
    return result
  }

  async function load() {
    if (!$activeProject) return
    loading = true
    loadErr = ''
    closeEditor()
    try {
      const res = await invoke('get_chunks', {
        project: $activeProject,
        page: 0,
        pageSize: ALL,
        approvedFilter: onlyUnapproved ? false : null,
      })
      items = res.items
      total = res.total
      collapsedKeys = new Set(groupItems(items).map(g => g.key))
    } catch (e) {
      console.error(e)
      loadErr = String(e)
      items = []
      total = 0
    } finally {
      loading = false
    }
  }

  function setFilter(unapprovedOnly) {
    if (onlyUnapproved === unapprovedOnly) return
    onlyUnapproved = unapprovedOnly
    load()
  }

  function toggleGroup(key) {
    if (collapsedKeys.has(key)) collapsedKeys.delete(key)
    else collapsedKeys.add(key)
    collapsedKeys = collapsedKeys
  }

  function expandAll() { collapsedKeys = new Set() }
  function collapseAll() { collapsedKeys = new Set(groups.map(g => g.key)) }

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
    if (ev === 'B1') return 'ev-b1'
    if (ev === 'B2') return 'ev-b2'
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
      collapsedKeys.delete(groupKey(chunk))
      collapsedKeys = collapsedKeys
    }
  }

  function closeEditor() {
    editingId = null
    draft = null
    errMsg = ''
    confirmingDelete = false
  }

  async function addNew() {
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
    collapsedKeys.delete(NO_TABLE_KEY)
    collapsedKeys = collapsedKeys
    await tick()
    document.getElementById(`row-${id}`)?.scrollIntoView({ block: 'center', behavior: 'smooth' })
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

  async function runExport(format, approvedOnly) {
    exportOpen = false
    exporting = true
    exportMsg = ''
    try {
      const path = await invoke('export_chunks', {
        project: $activeProject,
        format,
        approvedOnly,
      })
      exportMsg = path ? `Geëxporteerd naar ${path}` : ''
    } catch (e) {
      exportMsg = String(e)
    } finally {
      exporting = false
      if (exportMsg) setTimeout(() => { exportMsg = '' }, 6000)
    }
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
      <span class="total-badge">{total} aanbevelingen · {groups.length} tabellen</span>
    {/if}

    <div class="filter-toggle">
      <button class="filter-opt" class:active={!onlyUnapproved} on:click={() => setFilter(false)}>Alles</button>
      <button class="filter-opt" class:active={onlyUnapproved} on:click={() => setFilter(true)}>Niet geaccordeerd</button>
    </div>

    {#if groups.length > 0}
      <div class="filter-toggle">
        <button class="filter-opt" on:click={expandAll}>▾ Alles uitklappen</button>
        <button class="filter-opt" on:click={collapseAll}>▸ Alles inklappen</button>
      </div>
    {/if}

    <div class="export-wrap">
      <button class="btn-add" on:click={() => exportOpen = !exportOpen} disabled={!$activeProject || exporting}>
        {exporting ? 'Exporteren…' : '↓ Exporteren'}
      </button>
      {#if exportOpen}
        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <!-- svelte-ignore a11y-no-static-element-interactions -->
        <div class="export-backdrop" on:click={() => exportOpen = false}></div>
        <div class="export-menu">
          <span class="export-head">Alle aanbevelingen</span>
          <button on:click={() => runExport('csv', false)}>CSV — voor Excel</button>
          <button on:click={() => runExport('md', false)}>Markdown — leesbaar document</button>
          <button on:click={() => runExport('json', false)}>JSON — ruwe chunks</button>
          <span class="export-head">Alleen geaccordeerd</span>
          <button on:click={() => runExport('csv', true)}>CSV</button>
          <button on:click={() => runExport('md', true)}>Markdown</button>
          <button on:click={() => runExport('json', true)}>JSON</button>
        </div>
      {/if}
    </div>

    <button class="btn-add" on:click={addNew} disabled={!$activeProject}>+ Nieuwe aanbeveling</button>
  </div>

  {#if exportMsg}
    <p class="export-msg">{exportMsg}</p>
  {/if}

  {#if loading}
    <div class="loading-state">Laden…</div>
  {:else if items.length === 0}
    <div class="empty-state">
      <div class="empty-icon">◈</div>
      {#if loadErr}
        <p>Chunks konden niet worden geladen.</p>
        <p class="err-msg">{loadErr}</p>
      {:else if onlyUnapproved}
        <p>Alles is geaccordeerd. Niets meer te reviewen op deze pagina.</p>
      {:else}
        <p>Geen chunks gevonden. Voer stap 2 uit om aanbevelingen te extraheren.</p>
      {/if}
    </div>
  {:else}
    <div class="groups-wrap">
      {#each groups as group (group.key)}
        {@const isCollapsed = collapsedKeys.has(group.key)}
        <div class="table-group">
          <!-- svelte-ignore a11y-click-events-have-key-events -->
          <button class="group-header" on:click={() => toggleGroup(group.key)}>
            <span class="group-chevron">{isCollapsed ? '▸' : '▾'}</span>
            <span class="group-title">
              <span class="group-short">{group.short}</span>
              {#if group.rest}<span class="group-rest">{group.rest}</span>{/if}
            </span>
            <span class="group-count">{group.chunks.length}</span>
            <span class="group-approved" class:all-approved={group.approvedCount === group.chunks.length}>
              {group.approvedCount}/{group.chunks.length} ✓
            </span>
          </button>

          {#if !isCollapsed}
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
                  {#each group.chunks as chunk (chunk.id)}
                    <!-- svelte-ignore a11y-click-events-have-key-events -->
                    <!-- svelte-ignore a11y-no-noninteractive-element-interactions -->
                    <tr
                      id="row-{chunk.id}"
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
                              <button class="btn-source" on:click={() => pdfChunk = chunk}>
                                📄 Toon in PDF
                              </button>
                            </div>

                            <label class="approve-field">
                              <input type="checkbox" bind:checked={draft.approved} />
                              Geaccordeerd
                            </label>

                            <ReferenceList references={draft.references} refIds={chunk.metadata.ref_ids} />

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
          {/if}
        </div>
      {/each}
    </div>
  {/if}
</div>

{#if pdfChunk}
  <PdfViewer chunk={pdfChunk} on:close={() => pdfChunk = null} />
{/if}

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
    flex-wrap: wrap;
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
  .export-wrap { position: relative; margin-left: auto; }
  .export-wrap .btn-add { margin-left: 0; }

  /* Sits under the menu so a click anywhere else dismisses it. */
  .export-backdrop { position: fixed; inset: 0; z-index: 9; }

  .export-menu {
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 10;
    min-width: 236px;
    padding: 6px;
    display: flex;
    flex-direction: column;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow);
  }
  .export-head {
    padding: 7px 10px 4px;
    font-size: 10.5px; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; color: var(--text-3);
  }
  .export-menu button {
    padding: 7px 10px;
    border-radius: var(--radius);
    text-align: left;
    font-size: 12.5px;
    color: var(--text-2);
    transition: background .12s, color .12s;
  }
  .export-menu button:hover { background: var(--bg-hover); color: var(--text-1); }

  .export-msg {
    flex-shrink: 0;
    font-size: 12px;
    color: var(--text-2);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 7px 11px;
    user-select: text;
  }

  .btn-source {
    margin-left: auto;
    padding: 5px 11px;
    border-radius: var(--radius);
    border: 1px solid var(--accent);
    color: var(--accent-h);
    font-size: 11.5px;
    font-weight: 600;
    transition: background .12s;
  }
  .btn-source:hover { background: var(--accent-dim); }

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
    white-space: nowrap;
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

  /* Groups */
  .groups-wrap {
    flex: 1;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .table-group {
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    flex-shrink: 0;
  }

  .group-header {
    width: 100%;
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 11px 14px;
    background: var(--bg-card);
    cursor: pointer;
    text-align: left;
    transition: background .12s;
  }
  .group-header:hover { background: var(--bg-hover); }

  .group-chevron {
    align-self: center;
    font-size: 11px;
    color: var(--text-3);
    width: 10px;
    flex-shrink: 0;
  }
  .group-title {
    flex: 1;
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
  }
  .group-short {
    font-weight: 700;
    font-size: 13px;
    color: var(--text-1);
    white-space: nowrap;
    flex-shrink: 0;
  }
  .group-rest {
    font-size: 12px;
    color: var(--text-3);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }
  .group-count {
    flex-shrink: 0;
    padding: 2px 8px;
    border-radius: 3px;
    background: var(--bg-hover);
    color: var(--text-2);
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
  }
  .group-approved {
    flex-shrink: 0;
    padding: 2px 8px;
    border-radius: 3px;
    background: var(--bg-hover);
    color: var(--text-3);
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 700;
  }
  .group-approved.all-approved { background: var(--success); color: #fff; }

  /* Table */
  .table-wrap {
    overflow: auto;
    border-top: 1px solid var(--border);
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
  .chunk-row:last-child { border-bottom: none; }
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
  .ev-b1   { background: #35748f;               color: #eaf7fc; }
  .ev-b2   { background: #4c6272;               color: #eaf2f7; }
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
</style>
