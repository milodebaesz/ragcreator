<script>
  import { invoke } from '@tauri-apps/api/core'
  import { activeProject } from './stores.js'
  import { parseReference, pubmedUrl } from './references.js'

  let info = null
  let chunks = []
  let loading = false
  let loadErr = ''
  let refErr = ''

  // Filter on the two distributions. Either may be null ("alles"); set
  // together they intersect, so "Class I" + "A" shows only recommendations
  // that carry both.
  let selClass = null
  let selEvidence = null
  let expandedId = null

  const UNKNOWN = 'Onbekend'

  async function openRef(url) {
    refErr = ''
    try {
      await invoke('open_external', { url })
    } catch (e) {
      refErr = String(e)
    }
  }

  $: if ($activeProject) load()

  async function load() {
    if (!$activeProject) return
    loading = true
    loadErr = ''
    try {
      info = await invoke('get_guideline_info', { project: $activeProject })
      // The distributions come from the backend; the recommendations behind
      // them are needed here to list what a filter selects.
      const res = await invoke('get_chunks', {
        project: $activeProject,
        page: 0,
        pageSize: 100000,
        approvedFilter: null,
      })
      chunks = res.items
    } catch (e) {
      console.error(e)
      loadErr = String(e)
      info = null
      chunks = []
    } finally {
      loading = false
    }
  }

  // Empty metadata is bucketed the same way the backend counts it, so a bar
  // and its filter always select the same set.
  function labelOf(value) {
    const s = (value ?? '').trim()
    return s === '' ? UNKNOWN : s
  }

  function countBy(list, field) {
    const map = new Map()
    for (const c of list) {
      const key = labelOf(c.metadata?.[field])
      map.set(key, (map.get(key) ?? 0) + 1)
    }
    return map
  }

  function toggleClass(label) {
    selClass = selClass === label ? null : label
    expandedId = null
  }

  function toggleEvidence(label) {
    selEvidence = selEvidence === label ? null : label
    expandedId = null
  }

  function selectBoth(cls, ev) {
    const same = selClass === cls && selEvidence === ev
    selClass = same ? null : cls
    selEvidence = same ? null : ev
    expandedId = null
  }

  function clearFilter() {
    selClass = null
    selEvidence = null
    expandedId = null
  }

  // Each axis counts within the other axis's selection, so the two bar charts
  // read as one cross-tab rather than two independent totals.
  $: classSubset    = chunks.filter(c => !selEvidence || labelOf(c.metadata?.evidence) === selEvidence)
  $: evidenceSubset = chunks.filter(c => !selClass    || labelOf(c.metadata?.class)    === selClass)
  $: classCountMap    = countBy(classSubset, 'class')
  $: evidenceCountMap = countBy(evidenceSubset, 'evidence')

  $: filtered = chunks.filter(c =>
    (!selClass    || labelOf(c.metadata?.class)    === selClass) &&
    (!selEvidence || labelOf(c.metadata?.evidence) === selEvidence))

  $: hasFilter = selClass !== null || selEvidence !== null

  // Same colour mapping as the Resultaten tab, so a badge means the same thing
  // on both screens.
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

  function shortLabel(cls) {
    return cls.startsWith('Class ') ? cls.replace('Class ', '') : cls
  }

  function pct(part, whole) {
    if (!whole) return 0
    return Math.round((part / whole) * 100)
  }

  function splitTitle(title) {
    const idx = title.indexOf('—')
    if (idx === -1) return { short: title, rest: '' }
    return { short: title.slice(0, idx).trim(), rest: title.slice(idx + 1).trim() }
  }

  $: maxClass    = Math.max(1, ...(info?.class_counts ?? []).map(c => classCountMap.get(c.label) ?? 0))
  $: maxEvidence = Math.max(1, ...(info?.evidence_counts ?? []).map(c => evidenceCountMap.get(c.label) ?? 0))
</script>

<div class="info">
  <!-- Header -->
  <div class="info-header">
    <div class="header-left">
      <h2 class="info-title serif">Richtlijn</h2>
      {#if info?.guideline}
        <span class="name-badge">{info.guideline}{info.year ? ` · ${info.year}` : ''}</span>
      {/if}
    </div>
    <button class="refresh-btn" on:click={load} disabled={loading}>
      <span class:spinning={loading}>↺</span> Vernieuwen
    </button>
  </div>

  {#if loading && !info}
    <div class="loading-state">Laden…</div>
  {:else if loadErr}
    <div class="empty-state">
      <div class="empty-icon">◈</div>
      <p>Richtlijninformatie kon niet worden geladen.</p>
      <p class="err-msg">{loadErr}</p>
    </div>
  {:else if info && !info.has_chunks}
    <div class="empty-state">
      <div class="empty-icon">◈</div>
      <p>Nog geen geëxtraheerde inhoud voor dit project.</p>
      <p class="hint">Voer stap 1 en 2 van de pipeline uit om aanbevelingen te extraheren.</p>
    </div>
  {:else if info}
    <!-- Source line -->
    <div class="source-row">
      <span class="source-item">
        <span class="source-key">Bron</span>
        <span class="source-val">{info.pdf_name ?? 'Geen PDF gekoppeld'}</span>
      </span>
      <span class="source-item">
        <span class="source-key">Jaar</span>
        <span class="source-val">{info.year ?? '—'}</span>
      </span>
      <span class="source-item">
        <span class="source-key">Referenties in richtlijn</span>
        <span class="source-val">{info.guideline_reference_count || '—'}</span>
      </span>
      <span class="source-item">
        <span class="source-key">Geciteerde referenties</span>
        <span class="source-val">{info.cited_reference_count}</span>
      </span>
    </div>

    <!-- Headline numbers -->
    <div class="stat-grid">
      <div class="stat-card">
        <span class="stat-label">Tabellen</span>
        <span class="stat-value">{info.table_count}</span>
        <span class="stat-sub">aanbevelingstabellen in de richtlijn</span>
      </div>

      <div class="stat-card">
        <span class="stat-label">Aanbevelingen</span>
        <span class="stat-value">{info.recommendation_count}</span>
        <span class="stat-sub">
          {#if info.chunk_count !== info.recommendation_count}
            van {info.chunk_count} chunks totaal
          {:else}
            geëxtraheerd uit de richtlijn
          {/if}
        </span>
      </div>

      <div class="stat-card accent">
        <span class="stat-label">Level of Evidence A</span>
        <span class="stat-value">{info.evidence_a_count}</span>
        <span class="stat-sub">
          {pct(info.evidence_a_count, info.recommendation_count)}% van alle aanbevelingen
        </span>
      </div>

      <div class="stat-card">
        <span class="stat-label">Geaccordeerd</span>
        <span class="stat-value">{info.approved_count}</span>
        <span class="stat-sub">
          {pct(info.approved_count, info.chunk_count)}% gereviewd
        </span>
      </div>
    </div>

    <!-- Distributions -->
    <div class="panel-grid">
      <section class="panel">
        <h3 class="panel-title">
          Klasse-verdeling
          <span class="panel-hint">klik om te filteren</span>
        </h3>
        {#if info.class_counts.length === 0}
          <p class="panel-empty">Geen klassen vastgelegd.</p>
        {:else}
          <div class="bars">
            {#each info.class_counts as entry (entry.label)}
              {@const count = classCountMap.get(entry.label) ?? 0}
              <button
                class="bar-row"
                class:selected={selClass === entry.label}
                class:dimmed={count === 0}
                title="Toon alleen {entry.label}{selEvidence ? ` met evidence ${selEvidence}` : ''}"
                on:click={() => toggleClass(entry.label)}
              >
                <span class="badge {classColor(entry.label)}">{shortLabel(entry.label)}</span>
                <div class="bar-track">
                  <div class="bar-fill {classColor(entry.label)}" style="width: {pct(count, maxClass)}%"></div>
                </div>
                <span class="bar-count mono">
                  {count}{#if selEvidence}<span class="bar-total">/{entry.count}</span>{/if}
                </span>
              </button>
            {/each}
          </div>
        {/if}
      </section>

      <section class="panel">
        <h3 class="panel-title">
          Evidence-verdeling
          <span class="panel-hint">klik om te filteren</span>
        </h3>
        {#if info.evidence_counts.length === 0}
          <p class="panel-empty">Geen evidence-niveaus vastgelegd.</p>
        {:else}
          <div class="bars">
            {#each info.evidence_counts as entry (entry.label)}
              {@const count = evidenceCountMap.get(entry.label) ?? 0}
              <button
                class="bar-row"
                class:selected={selEvidence === entry.label}
                class:dimmed={count === 0}
                title="Toon alleen evidence {entry.label}{selClass ? ` binnen ${selClass}` : ''}"
                on:click={() => toggleEvidence(entry.label)}
              >
                <span class="badge {evidenceColor(entry.label)}">{entry.label}</span>
                <div class="bar-track">
                  <div class="bar-fill {evidenceColor(entry.label)}" style="width: {pct(count, maxEvidence)}%"></div>
                </div>
                <span class="bar-count mono">
                  {count}{#if selClass}<span class="bar-total">/{entry.count}</span>{/if}
                </span>
              </button>
            {/each}
          </div>
        {/if}
      </section>
    </div>

    <!-- Filtered recommendations -->
    {#if hasFilter}
      <section class="panel">
        <h3 class="panel-title">
          Aanbevelingen
          <span class="panel-count">{filtered.length}</span>
          <span class="filter-chips">
            {#if selClass}
              <button class="filter-chip" on:click={() => toggleClass(selClass)}>
                <span class="badge {classColor(selClass)}">{shortLabel(selClass)}</span> ×
              </button>
            {/if}
            {#if selEvidence}
              <button class="filter-chip" on:click={() => toggleEvidence(selEvidence)}>
                <span class="badge {evidenceColor(selEvidence)}">{selEvidence}</span> ×
              </button>
            {/if}
          </span>
          <button class="clear-btn" on:click={clearFilter}>Filter wissen</button>
        </h3>

        {#if filtered.length === 0}
          <p class="panel-empty">
            Geen aanbevelingen met {selClass ?? 'deze klasse'}{selClass && selEvidence ? ' én ' : ''}{selEvidence ? `evidence ${selEvidence}` : ''}.
          </p>
        {:else}
          <ul class="rec-list">
            {#each filtered as chunk (chunk.id)}
              {@const open = expandedId === chunk.id}
              <li class="rec">
                <button
                  class="rec-head"
                  on:click={() => expandedId = open ? null : chunk.id}
                >
                  <span class="badge {classColor(chunk.metadata.class)}">
                    {shortLabel(labelOf(chunk.metadata.class))}
                  </span>
                  <span class="badge {evidenceColor(chunk.metadata.evidence)}">
                    {labelOf(chunk.metadata.evidence)}
                  </span>
                  <span class="rec-text" class:full={open}>{chunk.text || '(leeg)'}</span>
                  {#if chunk.metadata.approved}
                    <span class="rec-ok" title="Geaccordeerd">✓</span>
                  {/if}
                </button>
                {#if open}
                  <div class="rec-meta">
                    <span class="rec-id mono">{chunk.id}</span>
                    {#if chunk.metadata.table_title}
                      <span class="rec-table">{chunk.metadata.table_title}</span>
                    {/if}
                    {#if chunk.metadata.ref_ids?.length}
                      <span class="rec-refs mono">ref. {chunk.metadata.ref_ids.join(', ')}</span>
                    {/if}
                  </div>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
      </section>
    {/if}

    <!-- Level of Evidence A per class -->
    <section class="panel">
      <h3 class="panel-title">
        Level of Evidence A per klasse
        <span class="panel-count">{info.evidence_a_count} aanbevelingen</span>
      </h3>
      {#if info.evidence_a_class_counts.length === 0}
        <p class="panel-empty">Geen aanbevelingen met Level of Evidence A.</p>
      {:else}
        <div class="chip-row">
          {#each info.evidence_a_class_counts as entry (entry.label)}
            <button
              class="chip"
              class:selected={selClass === entry.label && selEvidence === 'A'}
              title="Toon {entry.label} met evidence A"
              on:click={() => selectBoth(entry.label, 'A')}
            >
              <span class="badge {classColor(entry.label)}">{shortLabel(entry.label)}</span>
              <span class="chip-count mono">{entry.count}</span>
            </button>
          {/each}
        </div>
      {/if}
    </section>

    <!-- Evidence base -->
    <section class="panel">
      <h3 class="panel-title">
        Meest geciteerde bronnen
        <span class="panel-count">{info.cited_reference_count} unieke referenties</span>
      </h3>

      <div class="ref-quality">
        <span class="quality-item" class:bad={info.unresolved_reference_count > 0}>
          {info.unresolved_reference_count} citaatnummers zonder gevonden referentie
        </span>
        <span class="quality-item" class:bad={info.unreferenced_recommendation_count > 0}>
          {info.unreferenced_recommendation_count} aanbevelingen zonder citaat
        </span>
      </div>

      {#if info.top_references.length === 0}
        <p class="panel-empty">Nog geen opgeloste referenties. Voer stap 2 uit of vul referentienummers in bij Resultaten.</p>
      {:else}
        <ol class="top-refs">
          {#each info.top_references as usage (usage.id)}
            {@const ref = parseReference(usage.text)}
            <li class="top-ref">
              <span class="cite-count mono" title="{usage.count} aanbevelingen citeren deze bron">{usage.count}×</span>
              <button class="top-ref-title" on:click={() => openRef(pubmedUrl(ref))}>
                {ref.title ?? usage.text}
              </button>
              <span class="top-ref-src">{[ref.journal, ref.year].filter(Boolean).join(' ') || `ref. ${usage.id}`}</span>
            </li>
          {/each}
        </ol>
        {#if refErr}<p class="err-msg">{refErr}</p>{/if}
      {/if}
    </section>

    <!-- Per-table overview -->
    <section class="panel">
      <h3 class="panel-title">
        Tabellen
        <span class="panel-count">{info.table_count}</span>
      </h3>
      {#if info.tables.length === 0}
        <p class="panel-empty">Geen tabeltitels gevonden in de geëxtraheerde aanbevelingen.</p>
      {:else}
        <div class="table-wrap">
          <table class="table-list">
            <thead>
              <tr>
                <th class="col-title">Tabel</th>
                <th class="col-num">Aanbevelingen</th>
                <th class="col-num">LoE A</th>
                <th class="col-num">Geaccordeerd</th>
              </tr>
            </thead>
            <tbody>
              {#each info.tables as t (t.title)}
                {@const parts = splitTitle(t.title)}
                <tr>
                  <td class="col-title">
                    <span class="table-short">{parts.short}</span>
                    {#if parts.rest}<span class="table-rest">{parts.rest}</span>{/if}
                  </td>
                  <td class="col-num mono">{t.recommendation_count}</td>
                  <td class="col-num mono">
                    {#if t.evidence_a_count > 0}
                      <span class="badge ev-a">{t.evidence_a_count}</span>
                    {:else}
                      <span class="dash">—</span>
                    {/if}
                  </td>
                  <td class="col-num mono">
                    <span class:all-approved={t.approved_count === t.recommendation_count}>
                      {t.approved_count}/{t.recommendation_count}
                    </span>
                  </td>
                </tr>
              {/each}
            </tbody>
          </table>
        </div>
      {/if}
    </section>
  {/if}
</div>

<style>
  .info {
    padding: 24px 28px;
    overflow-y: auto;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  /* Header */
  .info-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-shrink: 0;
  }
  .header-left { display: flex; align-items: center; gap: 12px; min-width: 0; }
  .info-title  { font-size: 20px; font-weight: 600; }
  .name-badge {
    padding: 2px 9px;
    background: var(--accent-dim);
    color: var(--accent-h);
    border-radius: 3px;
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .refresh-btn {
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 6px 14px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    color: var(--text-2);
    font-size: 12px;
    flex-shrink: 0;
    transition: background .12s, color .12s;
  }
  .refresh-btn:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-1); }
  .refresh-btn:disabled { opacity: .5; cursor: not-allowed; }
  .refresh-btn .spinning { display: inline-block; animation: spin 1s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Source line */
  .source-row {
    display: flex;
    flex-wrap: wrap;
    gap: 10px 28px;
    padding: 12px 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .source-item { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .source-key {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .source-val {
    font-size: 13px;
    color: var(--text-1);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* Headline numbers */
  .stat-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 12px;
  }
  .stat-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 16px 18px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .stat-card.accent { border-color: var(--accent); }
  .stat-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .stat-value {
    font-family: var(--serif);
    font-size: 32px;
    line-height: 1.1;
    font-weight: 500;
  }
  .stat-card.accent .stat-value { color: var(--accent-h); }
  .stat-sub { font-size: 12px; color: var(--text-2); }

  /* Panels */
  .panel-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
    gap: 12px;
  }
  .panel {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 16px 18px;
  }
  .panel-title {
    display: flex;
    align-items: center;
    gap: 10px;
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 14px;
  }
  .panel-count {
    padding: 1px 8px;
    background: var(--bg-hover);
    color: var(--text-2);
    border-radius: 3px;
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
  }
  .panel-empty { font-size: 12.5px; color: var(--text-3); }

  /* Bars */
  .bars { display: flex; flex-direction: column; gap: 8px; }
  .bar-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 3px 6px;
    margin: 0 -6px;
    border-radius: var(--radius);
    border: 1px solid transparent;
    text-align: left;
    transition: background .12s, border-color .12s, opacity .12s;
  }
  .bar-row:hover { background: var(--bg-hover); }
  .bar-row.selected { border-color: var(--accent); background: var(--accent-dim); }
  .bar-row.dimmed { opacity: .4; }
  .bar-total { color: var(--text-3); font-size: 11px; }
  .bar-row .badge { min-width: 42px; text-align: center; }
  .bar-track {
    flex: 1;
    height: 8px;
    background: var(--bg-base);
    border-radius: 4px;
    overflow: hidden;
  }
  .bar-fill { height: 100%; border-radius: 4px; }
  .bar-count {
    min-width: 34px;
    text-align: right;
    font-size: 12px;
    color: var(--text-2);
  }

  /* Chips */
  .chip-row { display: flex; flex-wrap: wrap; gap: 10px; }
  .chip {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .chip-count { font-size: 14px; font-weight: 600; }
  .chip:hover { background: var(--bg-hover); }
  .chip.selected { border-color: var(--accent); background: var(--accent-dim); }

  /* Filter header */
  .panel-hint { font-size: 11px; font-weight: 400; color: var(--text-3); }
  .filter-chips { display: flex; gap: 6px; }
  .filter-chip {
    display: flex; align-items: center; gap: 5px;
    padding: 2px 7px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-size: 11px; color: var(--text-3);
    transition: background .12s, color .12s;
  }
  .filter-chip:hover { background: var(--bg-hover); color: var(--text-1); }
  .clear-btn {
    margin-left: auto;
    padding: 3px 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-size: 11.5px;
    color: var(--text-2);
    transition: background .12s, color .12s;
  }
  .clear-btn:hover { background: var(--bg-hover); color: var(--text-1); }

  /* Filtered recommendations */
  .rec-list { list-style: none; display: flex; flex-direction: column; gap: 2px; }
  .rec { border-bottom: 1px solid var(--border); }
  .rec:last-child { border-bottom: none; }
  .rec-head {
    display: flex; align-items: baseline; gap: 10px;
    width: 100%; padding: 8px 6px;
    text-align: left; border-radius: var(--radius);
    transition: background .12s;
  }
  .rec-head:hover { background: var(--bg-hover); }
  .rec-head .badge { flex-shrink: 0; }
  .rec-text {
    flex: 1; min-width: 0;
    font-size: 12.5px; line-height: 1.5; color: var(--text-1);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .rec-text.full { white-space: normal; overflow: visible; }
  .rec-ok { flex-shrink: 0; color: var(--success); font-size: 12px; }
  .rec-meta {
    display: flex; flex-wrap: wrap; gap: 6px 14px;
    padding: 0 6px 10px 6px;
    font-size: 11.5px; color: var(--text-3);
  }
  .rec-table { font-style: italic; }

  /* Table overview */
  .table-wrap { overflow-x: auto; }
  .table-list {
    width: 100%;
    border-collapse: collapse;
    font-size: 13px;
  }
  .table-list th {
    text-align: left;
    padding: 0 12px 8px 0;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .08em;
    text-transform: uppercase;
    color: var(--text-3);
    border-bottom: 1px solid var(--border);
  }
  .table-list td {
    padding: 9px 12px 9px 0;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
  }
  .table-list tr:last-child td { border-bottom: none; }
  .col-title { min-width: 260px; }
  .col-num   { text-align: right; white-space: nowrap; width: 1%; padding-right: 0 !important; padding-left: 16px !important; }
  .table-list th.col-num { padding-left: 16px; padding-right: 0; }

  .table-short { display: block; color: var(--text-1); font-weight: 500; }
  .table-rest  { display: block; font-size: 12px; color: var(--text-3); }
  .dash        { color: var(--text-3); }
  .all-approved { color: var(--success); font-weight: 600; }

  .mono { font-family: var(--mono); }

  /* Badges — mirrors the Resultaten tab */
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
  .ev-nr   { background: var(--bg-hover);       color: var(--text-2); }

  /* States */
  .loading-state {
    padding: 40px;
    text-align: center;
    color: var(--text-3);
    font-size: 13px;
  }
  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 10px;
    padding: 60px 20px;
    color: var(--text-3);
    text-align: center;
  }
  .empty-icon { font-size: 28px; color: var(--border); }
  .hint    { font-size: 12.5px; }
  .err-msg { font-size: 12px; color: #d6897b; font-family: var(--mono); }

  /* Evidence base */
  .ref-quality { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 4px; }
  .quality-item {
    padding: 3px 9px; border-radius: 3px;
    background: var(--success-dim); color: var(--success);
    font-size: 11.5px; font-weight: 600;
  }
  .quality-item.bad { background: var(--warn-dim); color: var(--warn); }

  .top-refs { list-style: none; display: flex; flex-direction: column; }
  .top-ref {
    display: flex; align-items: baseline; gap: 10px;
    padding: 6px 8px; border-radius: var(--radius);
    transition: background .12s;
  }
  .top-ref:hover { background: var(--bg-hover); }
  .cite-count {
    flex-shrink: 0; min-width: 30px; text-align: right;
    font-size: 11px; font-weight: 700; color: var(--accent-h);
  }
  .top-ref-title {
    flex: 1; min-width: 0; text-align: left;
    font-size: 12.5px; line-height: 1.45; color: var(--text-1);
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    transition: color .12s;
  }
  .top-ref-title:hover { color: var(--accent-h); text-decoration: underline; }
  .top-ref-src {
    flex-shrink: 0; font-size: 11px; font-style: italic; color: var(--text-3);
  }
  .err-msg { font-size: 11.5px; color: #d6897b; }
</style>
