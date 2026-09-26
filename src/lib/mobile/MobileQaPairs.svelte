<script>
  // Reading the generated Q&A pairs on a phone.
  //
  // Same shape as MobileRecommendations: one screen, an always-present search
  // field, and an explicit "toon meer" button rather than infinite scroll.
  // Answers are shown by default — a page of bare questions is not readable,
  // and the answers are one to three sentences each. Tapping a question folds
  // it away again.
  import { invoke } from '@tauri-apps/api/core'

  export let project

  const PAGE_SIZE = 25

  let query = ''
  let items = []
  let total = 0     // pairs in the file
  let matched = 0   // pairs left after the query
  let page = 0
  let loading = false
  let err = ''
  // Inverted on purpose: a pair is open unless it is in here.
  let collapsed = new Set()

  $: filtering = Boolean(query.trim())
  $: hasMore = items.length < matched

  // Reload on project switch or a new query; `load` reads the reactive values
  // directly so this stays a single dependency list.
  $: project, query, reset()

  let debounce
  function reset() {
    clearTimeout(debounce)
    // A search per keystroke is a search per character on a phone keyboard.
    debounce = setTimeout(() => load(0), query ? 200 : 0)
  }

  async function load(nextPage) {
    if (!project) return
    loading = true
    err = ''
    try {
      const res = await invoke('get_qa_pairs', {
        project,
        page: nextPage,
        pageSize: PAGE_SIZE,
        query: query.trim() || null,
      })
      items = nextPage === 0 ? res.items : [...items, ...res.items]
      total = res.total
      matched = res.matched
      page = nextPage
      if (nextPage === 0) collapsed = new Set()
    } catch (e) {
      err = String(e)
      items = []
      total = 0
      matched = 0
    } finally {
      loading = false
    }
  }

  function toggle(i) {
    if (collapsed.has(i)) collapsed.delete(i)
    else collapsed.add(i)
    collapsed = collapsed
  }
</script>

<div class="screen">
  <div class="bar">
    <input
      class="search"
      type="search"
      bind:value={query}
      placeholder="Zoek in vragen en antwoorden…"
      autocapitalize="none"
      autocorrect="off"
    />

    <div class="count">
      {#if loading && !items.length}
        Laden…
      {:else if filtering}
        {matched} {matched === 1 ? 'treffer' : 'treffers'}
        <button class="clear" on:click={() => (query = '')}>wissen</button>
      {:else}
        {total} Q&amp;A-paren
      {/if}
    </div>
  </div>

  <div class="list">
    {#if err}
      <p class="err">{err}</p>
    {:else if !loading && !items.length}
      <p class="empty">
        {#if filtering}
          Niets gevonden. Pas je zoekterm aan.
        {:else}
          Nog geen Q&amp;A-paren voor deze richtlijn. Draai stap 3 op de Mac en
          synchroniseer opnieuw naar iCloud.
        {/if}
      </p>
    {/if}

    {#each items as pair, i}
      {@const open = !collapsed.has(i)}
      <div class="card">
        <button class="q" on:click={() => toggle(i)}>
          <span class="mark">V</span>
          <span class="q-text">{pair.question || '(geen vraag)'}</span>
          <span class="chevron">{open ? '▾' : '▸'}</span>
        </button>

        {#if open}
          <div class="a">
            <p class="a-text">{pair.answer || '(geen antwoord)'}</p>
            <div class="tags">
              {#if pair.metadata?.section}
                <span class="tag section">{pair.metadata.section}</span>
              {/if}
              {#if pair.metadata?.disease}<span class="tag">{pair.metadata.disease}</span>{/if}
              {#if pair.metadata?.topic}<span class="tag">{pair.metadata.topic}</span>{/if}
              {#if pair.metadata?.chunk_id}<span class="tag mono">{pair.metadata.chunk_id}</span>{/if}
            </div>
          </div>
        {/if}
      </div>
    {/each}

    {#if hasMore}
      <button class="more" on:click={() => load(page + 1)} disabled={loading}>
        {loading ? 'Laden…' : `Toon meer (${items.length} van ${matched})`}
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

  .search {
    width: 100%;
    min-height: 44px;
    /* 16px keeps iOS from zooming the viewport when the field takes focus. */
    font-size: 16px;
  }

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

  .card {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    background: var(--bg-surface);
    overflow: hidden;
    /* The list is a scrolling column flexbox: without this the cards shrink
       to share the screen height instead of scrolling. */
    flex-shrink: 0;
  }

  .q {
    display: flex;
    align-items: flex-start;
    gap: 10px;
    width: 100%;
    /* 44px is Apple's minimum touch target; the padding gets there on its own
       for a one-line question and grows with a longer one. */
    padding: 13px 14px;
    text-align: left;
    color: var(--text-1);
    font-size: 14.5px;
    line-height: 1.45;
    font-weight: 600;
  }
  .mark {
    flex-shrink: 0;
    width: 20px;
    height: 20px;
    margin-top: 1px;
    border-radius: 5px;
    background: var(--accent-dim);
    color: var(--accent-h);
    font-size: 11px;
    font-weight: 700;
    line-height: 20px;
    text-align: center;
  }
  .q-text { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  .chevron { flex-shrink: 0; color: var(--text-3); font-size: 12px; margin-top: 3px; }

  .a { padding: 0 14px 13px 44px; min-width: 0; }
  .a-text {
    overflow-wrap: anywhere;
    color: var(--text-2);
    font-size: 14.5px;
    line-height: 1.65;
  }

  .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; min-width: 0; }
  .tag {
    padding: 3px 8px;
    border: 1px solid var(--border);
    border-radius: 999px;
    color: var(--text-3);
    font-size: 11px;
    /* A section title is long enough to be wider than the phone. A flex item
       will not shrink below its min-content width on its own, so without this
       one tag stretches the card past the screen edge and takes every line of
       text with it. */
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .tag.section { color: var(--text-2); }
  .tag.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }

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
