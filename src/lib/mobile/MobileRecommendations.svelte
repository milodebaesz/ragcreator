<script>
  // Browsing and searching the recommendations.
  //
  // One screen rather than a separate browse and search tab: on a phone the
  // filter bar is the same either way, and an empty query simply means "show
  // everything". Paging is by an explicit button — an infinite scroll would
  // fight the sticky filter bar and lose the reader's place.
  import { invoke } from '@tauri-apps/api/core'
  import RecCard from './RecCard.svelte'

  export let project

  const PAGE_SIZE = 25
  const CLASS_OPTIONS   = ['', 'Class I', 'Class IIa', 'Class IIb', 'Class III']
  const DISEASE_OPTIONS = ['', 'HCM', 'DCM', 'ARVC', 'RCM', 'CAD', 'HF', 'AF', 'VT', 'VHD', 'ACS', 'general']
  const TOPIC_OPTIONS   = ['', 'diagnosis', 'treatment', 'risk_stratification', 'screening', 'lifestyle', 'follow_up', 'general']

  let query = ''
  let classFilter = ''
  let diseaseFilter = ''
  let topicFilter = ''
  let showFilters = false

  let items = []
  let total = 0
  let page = 0
  let loading = false
  let err = ''

  $: filtering = Boolean(query.trim() || classFilter || diseaseFilter || topicFilter)
  $: activeFilterCount = [classFilter, diseaseFilter, topicFilter].filter(Boolean).length

  // Reload whenever the project or any filter changes; `load` reads the
  // reactive values directly so this stays a single dependency list.
  $: project, query, classFilter, diseaseFilter, topicFilter, reset()

  let debounce
  function reset() {
    clearTimeout(debounce)
    // Typing a query hits the backend on every keystroke otherwise, which on a
    // phone keyboard is a search per character.
    debounce = setTimeout(() => load(0), query ? 200 : 0)
  }

  async function load(nextPage) {
    if (!project) return
    loading = true
    err = ''
    try {
      if (filtering) {
        // search_chunks returns its own capped result set, so there is nothing
        // to page through.
        const found = await invoke('search_chunks', {
          project,
          query,
          classFilter: classFilter || null,
          diseaseFilter: diseaseFilter || null,
          topicFilter: topicFilter || null,
        })
        items = found
        total = found.length
        page = 0
      } else {
        const res = await invoke('get_chunks', {
          project,
          page: nextPage,
          pageSize: PAGE_SIZE,
          approvedFilter: null,
        })
        items = nextPage === 0 ? res.items : [...items, ...res.items]
        total = res.total
        page = nextPage
      }
    } catch (e) {
      err = String(e)
      items = []
      total = 0
    } finally {
      loading = false
    }
  }

  function clearAll() {
    query = ''
    classFilter = ''
    diseaseFilter = ''
    topicFilter = ''
  }

  $: hasMore = !filtering && items.length < total
</script>

<div class="screen">
  <div class="bar">
    <div class="search-row">
      <input
        class="search"
        type="search"
        bind:value={query}
        placeholder="Zoek in aanbevelingen…"
        autocapitalize="none"
        autocorrect="off"
      />
      <button
        class="filter-btn"
        class:on={showFilters || activeFilterCount > 0}
        on:click={() => (showFilters = !showFilters)}
      >
        Filters{activeFilterCount ? ` (${activeFilterCount})` : ''}
      </button>
    </div>

    {#if showFilters}
      <div class="filters">
        <select bind:value={classFilter}>
          {#each CLASS_OPTIONS as opt}
            <option value={opt}>{opt || 'Alle klassen'}</option>
          {/each}
        </select>
        <select bind:value={diseaseFilter}>
          {#each DISEASE_OPTIONS as opt}
            <option value={opt}>{opt || 'Alle aandoeningen'}</option>
          {/each}
        </select>
        <select bind:value={topicFilter}>
          {#each TOPIC_OPTIONS as opt}
            <option value={opt}>{opt || 'Alle onderwerpen'}</option>
          {/each}
        </select>
      </div>
    {/if}

    <div class="count">
      {#if loading && !items.length}
        Laden…
      {:else if filtering}
        {total} {total === 1 ? 'treffer' : 'treffers'}
        <button class="clear" on:click={clearAll}>wissen</button>
      {:else}
        {total} aanbevelingen
      {/if}
    </div>
  </div>

  <div class="list">
    {#if err}
      <p class="err">{err}</p>
    {:else if !loading && !items.length}
      <p class="empty">
        {filtering ? 'Niets gevonden. Pas je zoekterm of filters aan.' : 'Geen aanbevelingen in dit project.'}
      </p>
    {/if}

    {#each items as chunk (chunk.id)}
      <RecCard {chunk} {project} query={query.trim()} />
    {/each}

    {#if hasMore}
      <button class="more" on:click={() => load(page + 1)} disabled={loading}>
        {loading ? 'Laden…' : `Toon meer (${items.length} van ${total})`}
      </button>
    {/if}
  </div>
</div>

<style>
  .screen { display: flex; flex-direction: column; height: 100%; overflow: hidden; }

  .bar {
    flex-shrink: 0;
    padding: 10px 16px 8px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
  }

  .search-row { display: flex; gap: 8px; }
  .search {
    flex: 1;
    min-height: 44px;
    /* 16px keeps iOS from zooming the viewport when the field takes focus. */
    font-size: 16px;
  }
  .filter-btn {
    flex-shrink: 0;
    padding: 0 14px;
    min-height: 44px;
    font-size: 13.5px;
    font-weight: 600;
    color: var(--text-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .filter-btn.on { color: var(--accent-h); border-color: var(--accent); background: var(--accent-dim); }

  .filters { display: flex; flex-direction: column; gap: 8px; margin-top: 8px; }
  .filters select { min-height: 44px; font-size: 16px; }

  .count {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 8px;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: var(--text-3);
  }
  .clear { color: var(--accent-h); font-size: 12px; text-decoration: underline; }

  .list {
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding: 12px 16px calc(24px + env(safe-area-inset-bottom));
    display: flex;
    flex-direction: column;
    gap: 10px;
  }

  .empty, .err { padding: 40px 8px; text-align: center; color: var(--text-3); font-size: 14px; }
  .err { color: #d6897b; }

  .more {
    margin-top: 4px;
    min-height: 48px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--text-2);
    font-size: 14px;
    font-weight: 600;
  }
</style>
