<script>
  import { invoke } from '@tauri-apps/api/core'
  import { activeProject } from './stores.js'

  const PAGE_SIZE = 25

  let items = []
  let total = 0        // pairs in the file
  let matched = 0      // pairs left after the query
  let page = 0
  let query = ''
  let loading = false
  let loadErr = ''
  // Inverted on purpose: a pair is open unless it is in here. A page of bare
  // questions is not readable — the answer is the thing you came for, and
  // collapsing is the exception, not the default.
  let collapsed = new Set()

  // Reload on project switch; reset paging so page 3 of a previous project
  // never leaks into a project that only has one page.
  $: if ($activeProject) resetAndLoad($activeProject)

  $: pageCount = Math.max(1, Math.ceil(matched / PAGE_SIZE))

  function resetAndLoad(_project) {
    page = 0
    query = ''
    load()
  }

  async function load() {
    if (!$activeProject) return
    loading = true
    loadErr = ''
    collapsed = new Set()
    try {
      const res = await invoke('get_qa_pairs', {
        project: $activeProject,
        page,
        pageSize: PAGE_SIZE,
        query: query.trim() || null,
      })
      items = res.items
      total = res.total
      matched = res.matched
    } catch (e) {
      console.error(e)
      loadErr = String(e)
      items = []
      total = 0
      matched = 0
    } finally {
      loading = false
    }
  }

  function search() {
    page = 0
    load()
  }

  function clearQuery() {
    query = ''
    search()
  }

  function onKey(e) {
    if (e.key === 'Enter') search()
  }

  function goto(next) {
    const clamped = Math.min(Math.max(next, 0), pageCount - 1)
    if (clamped === page) return
    page = clamped
    load()
  }

  function toggle(idx) {
    if (collapsed.has(idx)) collapsed.delete(idx)
    else collapsed.add(idx)
    collapsed = collapsed
  }

  function expandAll() {
    collapsed = new Set()
  }

  function collapseAll() {
    collapsed = new Set(items.map((_, i) => i))
  }

  async function copyPair(pair) {
    try {
      await navigator.clipboard.writeText(`Q: ${pair.question}\nA: ${pair.answer}`)
    } catch (e) {
      console.error(e)
    }
  }
</script>

<div class="qa-page">
  <!-- Header -->
  <div class="qa-header">
    <h2 class="qa-title serif">Q&amp;A-paren</h2>
    {#if total > 0}
      <span class="total-badge">
        {#if matched === total}
          {total} paren
        {:else}
          {matched} van {total} paren
        {/if}
      </span>
    {/if}

    <div class="spacer"></div>

    {#if items.length > 0}
      <div class="filter-toggle">
        <button class="filter-opt" on:click={expandAll}>▾ Alles uitklappen</button>
        <button class="filter-opt" on:click={collapseAll}>▸ Alles inklappen</button>
      </div>
    {/if}
  </div>

  <!-- Search -->
  <div class="search-bar">
    <div class="search-input-wrap">
      <span class="search-icon">⌕</span>
      <input
        class="search-input"
        bind:value={query}
        on:keydown={onKey}
        placeholder="Zoek in vragen, antwoorden en secties…"
      />
      {#if query}
        <button class="clear-btn" on:click={clearQuery} title="Wissen">✕</button>
      {/if}
    </div>
    <button class="btn-search" on:click={search} disabled={loading}>Zoeken</button>
  </div>

  <!-- Content -->
  {#if loading}
    <div class="state-box">Laden…</div>
  {:else if loadErr}
    <div class="state-box error">
      <div class="empty-icon">⚠</div>
      <p>Q&amp;A-paren konden niet worden geladen.</p>
      <p class="err-msg">{loadErr}</p>
    </div>
  {:else if total === 0}
    <div class="state-box">
      <div class="empty-icon">◈</div>
      <p>Nog geen Q&amp;A-paren voor dit project.</p>
      <p class="hint">Draai stap 3 (“Q&amp;A genereren”) in de Pipeline-tab.</p>
    </div>
  {:else if items.length === 0}
    <div class="state-box">
      <div class="empty-icon">◈</div>
      <p>Geen paren gevonden voor “{query}”.</p>
    </div>
  {:else}
    <div class="qa-list">
      {#each items as pair, i}
        {@const open = !collapsed.has(i)}
        <div class="qa-card">
          <!-- svelte-ignore a11y-click-events-have-key-events -->
          <button class="qa-question" on:click={() => toggle(i)}>
            <span class="chevron">{open ? '▾' : '▸'}</span>
            <span class="q-mark">Q</span>
            <span class="q-text">{pair.question || '(geen vraag)'}</span>
          </button>

          {#if open}
            <div class="qa-body">
              <div class="answer">
                <span class="a-mark">A</span>
                <p class="a-text">{pair.answer || '(geen antwoord)'}</p>
              </div>

              <div class="meta-row">
                {#if pair.metadata?.section}
                  <span class="tag section" title="Sectie">{pair.metadata.section}</span>
                {/if}
                {#if pair.metadata?.disease}
                  <span class="tag">{pair.metadata.disease}</span>
                {/if}
                {#if pair.metadata?.topic}
                  <span class="tag">{pair.metadata.topic}</span>
                {/if}
                {#if pair.metadata?.type}
                  <span class="tag">{pair.metadata.type}</span>
                {/if}
                {#if pair.metadata?.chunk_id}
                  <span class="tag mono" title="Bron-chunk">{pair.metadata.chunk_id}</span>
                {/if}
                <div class="spacer"></div>
                <button class="copy-btn" on:click={() => copyPair(pair)}>Kopieer Q&amp;A</button>
              </div>
            </div>
          {/if}
        </div>
      {/each}
    </div>

    {#if pageCount > 1}
      <div class="pager">
        <button class="page-btn" on:click={() => goto(page - 1)} disabled={page === 0}>← Vorige</button>
        <span class="page-info">Pagina {page + 1} van {pageCount}</span>
        <button class="page-btn" on:click={() => goto(page + 1)} disabled={page >= pageCount - 1}>Volgende →</button>
      </div>
    {/if}
  {/if}
</div>

<style>
  .qa-page {
    padding: 24px 28px;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 16px;
    overflow: hidden;
  }

  /* Header */
  .qa-header {
    display: flex;
    align-items: center;
    gap: 14px;
    flex-shrink: 0;
  }
  .qa-title { font-size: 20px; font-weight: 500; }
  .spacer { flex: 1; }

  .total-badge {
    font-size: 11.5px;
    color: var(--text-2);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 999px;
    padding: 3px 11px;
  }

  .filter-toggle {
    display: flex;
    gap: 2px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 2px;
  }
  .filter-opt {
    padding: 5px 11px;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-3);
    border-radius: 3px;
    transition: background .12s, color .12s;
  }
  .filter-opt:hover { background: var(--bg-hover); color: var(--text-1); }

  /* Search */
  .search-bar { display: flex; gap: 10px; flex-shrink: 0; }
  .search-input-wrap { flex: 1; position: relative; display: flex; align-items: center; }
  .search-icon { position: absolute; left: 13px; color: var(--text-3); pointer-events: none; }
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

  /* States */
  .state-box {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    color: var(--text-3);
    font-size: 13px;
    text-align: center;
  }
  .empty-icon { font-size: 26px; color: var(--border); }
  .hint { font-size: 12px; color: var(--text-3); }
  .err-msg {
    font-family: var(--mono);
    font-size: 11.5px;
    color: #d6897b;
    max-width: 560px;
    word-break: break-word;
  }

  /* List */
  .qa-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding-right: 4px;
  }

  .qa-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    overflow: hidden;
    transition: border-color .12s;
    /* .qa-list is a column flexbox that scrolls, so without this every card
       shrinks to share the visible height and `overflow: hidden` clips the
       text away — a page of empty slivers. */
    flex-shrink: 0;
  }
  .qa-card:hover { border-color: var(--text-3); }

  .qa-question {
    width: 100%;
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding: 12px 14px;
    text-align: left;
    font-size: 14px;
    line-height: 1.5;
    transition: background .12s;
  }
  .qa-question:hover { background: var(--bg-hover); }
  .chevron { color: var(--text-3); font-size: 10px; flex-shrink: 0; }
  .q-mark, .a-mark {
    flex-shrink: 0;
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 700;
    color: var(--accent-h);
    background: var(--accent-dim);
    border-radius: 3px;
    padding: 2px 6px;
  }
  .a-mark { color: var(--success); background: var(--success-dim); }
  .q-text { color: var(--text-1); font-weight: 600; }

  .qa-body {
    padding: 0 14px 12px 14px;
    border-top: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    gap: 10px;
  }
  .answer {
    display: flex;
    align-items: baseline;
    gap: 10px;
    padding-top: 12px;
  }
  .a-text {
    font-size: 14px;
    /* Prose, not a table cell: looser leading and a measure that stops the
       line from running the full width of a maximised window. */
    line-height: 1.65;
    max-width: 78ch;
    color: var(--text-1);
    user-select: text;
  }

  .meta-row {
    display: flex;
    align-items: center;
    gap: 6px;
    flex-wrap: wrap;
  }
  .tag {
    font-size: 10.5px;
    color: var(--text-2);
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: 3px;
    padding: 2px 7px;
  }
  .tag.section { color: var(--text-2); max-width: 420px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .mono { font-family: var(--mono); }

  .copy-btn {
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-3);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 4px 10px;
    transition: background .12s, color .12s, border-color .12s;
  }
  .copy-btn:hover { background: var(--accent-dim); color: var(--accent-h); border-color: var(--accent); }

  /* Pager */
  .pager {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 16px;
    flex-shrink: 0;
    padding-top: 4px;
  }
  .page-btn {
    padding: 6px 14px;
    font-size: 12px;
    font-weight: 600;
    color: var(--text-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    transition: background .12s, color .12s;
  }
  .page-btn:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-1); }
  .page-btn:disabled { opacity: .4; cursor: not-allowed; }
  .page-info { font-size: 12px; color: var(--text-3); }
</style>
