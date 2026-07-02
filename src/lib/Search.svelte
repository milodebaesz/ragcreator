<script>
  import { invoke } from '@tauri-apps/api/core'
  import { activeProject } from './stores.js'

  let query      = ''
  let classFilter   = ''
  let diseaseFilter = ''
  let topicFilter   = ''
  let results    = []
  let searching  = false
  let searched   = false
  let expanded   = null

  const CLASS_OPTIONS   = ['', 'Class I', 'Class IIa', 'Class IIb', 'Class III']
  const DISEASE_OPTIONS = ['', 'HCM', 'DCM', 'ARVC', 'RCM', 'CAD', 'HF', 'AF', 'VT', 'VHD', 'ACS', 'general']
  const TOPIC_OPTIONS   = ['', 'diagnosis', 'treatment', 'risk_stratification', 'screening', 'lifestyle', 'follow_up', 'general']

  async function search() {
    if (!$activeProject) return
    searching = true
    searched  = true
    expanded  = null
    try {
      results = await invoke('search_chunks', {
        project:       $activeProject,
        query,
        classFilter:   classFilter   || null,
        diseaseFilter: diseaseFilter || null,
        topicFilter:   topicFilter   || null,
      })
    } catch (e) {
      console.error(e)
      results = []
    } finally {
      searching = false
    }
  }

  function onKey(e) {
    if (e.key === 'Enter') search()
  }

  function clearFilters() {
    query = ''; classFilter = ''; diseaseFilter = ''; topicFilter = ''
    results = []; searched = false
  }

  function classColor(cls) {
    if (!cls) return 'neutral'
    if (cls.includes('IIa')) return 'class2a'
    if (cls.includes('IIb')) return 'class2b'
    if (cls.includes('III')) return 'class3'
    if (cls.includes('I'))   return 'class1'
    return 'neutral'
  }

  function highlight(text, q) {
    if (!q.trim()) return text
    const re = new RegExp(`(${q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
    return text.replace(re, '<mark>$1</mark>')
  }
</script>

<div class="search-page">
  <!-- Search bar -->
  <div class="search-bar">
    <div class="search-input-wrap">
      <svg class="search-icon" width="15" height="15" viewBox="0 0 16 16" fill="none"><circle cx="7" cy="7" r="4.5" stroke="currentColor" stroke-width="1.3"/><path d="M13.5 13.5 10.5 10.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/></svg>
      <input
        class="search-input"
        bind:value={query}
        placeholder="Zoek in aanbevelingen… (Enter om te zoeken)"
        on:keydown={onKey}
      />
      {#if query}
        <button class="clear-btn" on:click={clearFilters}>✕</button>
      {/if}
    </div>

    <button class="btn-search" on:click={search} disabled={searching}>
      {searching ? 'Zoeken…' : 'Zoeken'}
    </button>
  </div>

  <!-- Filters -->
  <div class="filters">
    <label class="filter-group">
      <span class="filter-label">Klasse</span>
      <select bind:value={classFilter} on:change={search}>
        {#each CLASS_OPTIONS as opt}
          <option value={opt}>{opt || 'Alle klassen'}</option>
        {/each}
      </select>
    </label>

    <label class="filter-group">
      <span class="filter-label">Ziekte</span>
      <select bind:value={diseaseFilter} on:change={search}>
        {#each DISEASE_OPTIONS as opt}
          <option value={opt}>{opt || 'Alle ziektes'}</option>
        {/each}
      </select>
    </label>

    <label class="filter-group">
      <span class="filter-label">Onderwerp</span>
      <select bind:value={topicFilter} on:change={search}>
        {#each TOPIC_OPTIONS as opt}
          <option value={opt}>{opt || 'Alle onderwerpen'}</option>
        {/each}
      </select>
    </label>

    {#if searched}
      <span class="result-count">
        {results.length} {results.length === 1 ? 'resultaat' : 'resultaten'}
        {results.length === 200 ? '(max)' : ''}
      </span>
    {/if}
  </div>

  <!-- Results -->
  <div class="results-list">
    {#if searching}
      <div class="state-msg">Zoeken…</div>
    {:else if searched && results.length === 0}
      <div class="state-msg">Geen resultaten gevonden.</div>
    {:else if !searched}
      <div class="state-msg hint">
        Voer een zoekterm in of selecteer een filter om te starten.
      </div>
    {:else}
      {#each results as chunk}
        <div
          class="result-card"
          class:open={expanded === chunk.id}
          on:click={() => expanded = expanded === chunk.id ? null : chunk.id}
          role="button"
          tabindex="0"
          on:keydown={e => e.key === 'Enter' && (expanded = expanded === chunk.id ? null : chunk.id)}
        >
          <div class="result-header">
            <div class="result-badges">
              {#if chunk.metadata.class}
                <span class="badge {classColor(chunk.metadata.class)}">
                  {chunk.metadata.class}
                </span>
              {/if}
              {#if chunk.metadata.evidence}
                <span class="badge ev">Ev. {chunk.metadata.evidence}</span>
              {/if}
              {#if chunk.metadata.disease}
                <span class="tag">{chunk.metadata.disease}</span>
              {/if}
              {#if chunk.metadata.topic}
                <span class="tag topic">{chunk.metadata.topic}</span>
              {/if}
            </div>
            <span class="result-id mono">{chunk.id}</span>
          </div>

          <p class="result-text">
            <!-- eslint-disable-next-line svelte/no-at-html-tags -->
            {@html highlight(
              expanded === chunk.id ? chunk.text : chunk.text.slice(0, 200) + (chunk.text.length > 200 ? '…' : ''),
              query
            )}
          </p>

          {#if expanded === chunk.id && chunk.metadata.section}
            <p class="result-section">Sectie: {chunk.metadata.section}</p>
          {/if}
        </div>
      {/each}
    {/if}
  </div>
</div>

<style>
  .search-page {
    padding: 24px 28px;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 16px;
    overflow: hidden;
  }

  /* Search bar */
  .search-bar {
    display: flex;
    gap: 10px;
    flex-shrink: 0;
  }
  .search-input-wrap {
    flex: 1;
    position: relative;
    display: flex;
    align-items: center;
  }
  .search-icon {
    position: absolute;
    left: 13px;
    color: var(--text-3);
    pointer-events: none;
  }
  .search-input {
    width: 100%;
    padding: 10px 36px 10px 38px;
    font-size: 14px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    transition: border-color .15s;
  }
  .search-input:focus { border-color: var(--accent); }
  .clear-btn {
    position: absolute;
    right: 10px;
    color: var(--text-3);
    font-size: 13px;
    padding: 4px 6px;
    border-radius: 4px;
    transition: background .12s;
  }
  .clear-btn:hover { background: var(--bg-hover); color: var(--text-1); }

  .btn-search {
    padding: 10px 22px;
    background: var(--accent);
    color: #fff;
    border-radius: var(--radius);
    font-weight: 600;
    font-size: 14px;
    transition: background .12s, opacity .12s;
    flex-shrink: 0;
  }
  .btn-search:hover    { background: var(--accent-h); }
  .btn-search:disabled { opacity: .5; cursor: not-allowed; }

  /* Filters */
  .filters {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-wrap: wrap;
    flex-shrink: 0;
  }
  .filter-group {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .filter-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .07em;
    text-transform: uppercase;
    color: var(--text-3);
  }
  .filter-group select {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-1);
    font-size: 12px;
    padding: 5px 10px;
    outline: none;
    cursor: pointer;
    transition: border-color .15s;
  }
  .filter-group select:focus { border-color: var(--accent); }

  .result-count {
    margin-left: auto;
    font-size: 12px;
    color: var(--text-3);
  }

  /* Results list */
  .results-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 8px;
  }

  .state-msg {
    padding: 40px 0;
    text-align: center;
    color: var(--text-3);
    font-size: 14px;
  }
  .state-msg.hint { color: var(--text-3); }

  .result-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    cursor: pointer;
    transition: border-color .15s, background .15s;
  }
  .result-card:hover { border-color: var(--accent); background: var(--bg-hover); }
  .result-card.open  { border-color: var(--accent); }

  .result-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 8px;
  }
  .result-badges { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }

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
  .neutral { background: var(--bg-hover); color: var(--text-1); }
  .ev      { background: var(--accent); color: #fff; }

  .tag {
    font-size: 11px;
    padding: 2px 7px;
    border-radius: 3px;
    background: var(--bg-hover);
    color: var(--text-3);
  }
  .tag.topic { color: var(--text-2); }

  .result-id  { font-family: var(--mono); font-size: 11px; color: var(--text-3); }
  .result-text {
    font-size: 13px;
    color: var(--text-2);
    line-height: 1.6;
    white-space: pre-wrap;
  }
  .result-section {
    margin-top: 8px;
    font-size: 11px;
    color: var(--text-3);
    font-style: italic;
  }

  :global(.result-text mark) {
    background: rgba(201,144,63,.35);
    color: var(--accent-h);
    border-radius: 2px;
  }
</style>
