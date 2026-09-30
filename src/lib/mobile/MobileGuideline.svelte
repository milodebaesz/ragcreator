<script>
  // Reading the guideline itself.
  //
  // guideline.md is several hundred kilobytes, so it is never handed to the
  // webview whole: the backend serves an outline and then one section at a
  // time. Typing in the field searches the full text and jumps straight to the
  // section a hit lives in.
  import { invoke } from '@tauri-apps/api/core'
  import { renderMarkdown } from '../markdown.js'
  import PdfReader from './PdfReader.svelte'
  import { rememberedPage } from './pdf.js'

  export let project

  /** 'pdf' reads the guideline as published; 'text' is searchable. */
  let mode = 'pdf'

  let outline = []
  let hits = []
  let query = ''
  let section = null
  let loading = false
  let err = ''
  /** The scroll container, reset to the top on every section change. */
  let reader

  $: project, loadOutline()

  async function loadOutline() {
    if (!project) return
    loading = true
    err = ''
    section = null
    query = ''
    hits = []
    try {
      // Headings with no body are front matter from the PDF's title page —
      // listing them buries the actual chapters.
      const all = await invoke('get_guideline_outline', { project })
      outline = all.filter(s => s.length > 120)
    } catch (e) {
      err = String(e)
      outline = []
    } finally {
      loading = false
    }
  }

  let debounce
  function onQuery() {
    clearTimeout(debounce)
    debounce = setTimeout(runSearch, 250)
  }

  async function runSearch() {
    if (!query.trim()) {
      hits = []
      return
    }
    try {
      hits = await invoke('search_guideline', { project, query })
    } catch (e) {
      err = String(e)
      hits = []
    }
  }

  async function openSection(index) {
    loading = true
    err = ''
    try {
      section = await invoke('get_guideline_section', { project, index })
      // A new section starts at its own beginning, not wherever the previous
      // one was scrolled to.
      if (reader) reader.scrollTop = 0
    } catch (e) {
      err = String(e)
    } finally {
      loading = false
    }
  }

  function back() {
    section = null
  }
</script>

<div class="screen">
  <div class="modes" role="tablist">
    <button class:active={mode === 'pdf'} role="tab" aria-selected={mode === 'pdf'} on:click={() => (mode = 'pdf')}>PDF</button>
    <button class:active={mode === 'text'} role="tab" aria-selected={mode === 'text'} on:click={() => (mode = 'text')}>Tekst &amp; zoeken</button>
  </div>

  {#if mode === 'pdf'}
    <div class="pdf-pane">
      {#key project}
        <PdfReader {project} page={rememberedPage(project)} />
      {/key}
    </div>
  {:else if section}
    <div class="reader-bar">
      <button class="back" on:click={back}>‹ Inhoud</button>
      <div class="nav">
        <button disabled={!section.has_prev} on:click={() => openSection(section.index - 1)}>Vorige</button>
        <button disabled={!section.has_next} on:click={() => openSection(section.index + 1)}>Volgende</button>
      </div>
    </div>

    <div class="reader" bind:this={reader}>
      <h2 class="section-title serif">{section.title}</h2>
      {#if section.markdown}
        <div class="prose">{@html renderMarkdown(section.markdown)}</div>
      {:else}
        <p class="empty">Deze sectie bevat geen tekst.</p>
      {/if}
    </div>
  {:else}
    <div class="bar">
      <input
        class="search"
        type="search"
        bind:value={query}
        on:input={onQuery}
        placeholder="Zoek in de richtlijntekst…"
        autocapitalize="none"
        autocorrect="off"
      />
      <div class="count">
        {#if query.trim()}
          {hits.length} {hits.length === 1 ? 'sectie' : 'secties'} met treffers
        {:else}
          {outline.length} secties
        {/if}
      </div>
    </div>

    <div class="list">
      {#if err}
        <p class="err">{err}</p>
      {:else if loading}
        <p class="empty">Laden…</p>
      {:else if query.trim()}
        {#each hits as hit (hit.index)}
          <button class="hit" on:click={() => openSection(hit.index)}>
            <span class="hit-title">{hit.title}</span>
            <span class="hit-snippet">…{hit.snippet}…</span>
          </button>
        {:else}
          <p class="empty">Niets gevonden in de richtlijntekst.</p>
        {/each}
      {:else}
        {#each outline as s (s.index)}
          <button class="row depth-{s.depth}" on:click={() => openSection(s.index)}>
            <span class="row-title">{s.title}</span>
            <span class="chev">›</span>
          </button>
        {:else}
          <p class="empty">Geen guideline.md gesynchroniseerd voor dit project.</p>
        {/each}
      {/if}
    </div>
  {/if}
</div>

<style>
  .screen { display: flex; flex-direction: column; height: 100%; overflow: hidden; }

  .modes {
    flex-shrink: 0;
    display: flex;
    gap: 4px;
    margin: 8px 16px 0;
    padding: 3px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
  }
  .modes button {
    flex: 1 1 0;
    text-align: center;
    min-height: 36px;
    font-size: 13px;
    font-weight: 600;
    color: var(--text-3);
    border-radius: var(--radius);
  }
  .modes button.active { background: var(--accent-dim); color: var(--accent-h); }

  .pdf-pane { flex: 1; min-height: 0; margin-top: 8px; }

  .bar {
    flex-shrink: 0;
    padding: 10px 16px 8px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
  }
  .search { width: 100%; min-height: 44px; font-size: 16px; }
  .count {
    margin-top: 8px;
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: var(--text-3);
  }

  .list {
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: calc(16px + env(safe-area-inset-bottom));
  }

  .row, .hit {
    display: flex;
    width: 100%;
    text-align: left;
    align-items: center;
    gap: 10px;
    min-height: 50px;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }
  .row:active, .hit:active { background: var(--bg-hover); }

  .row-title { flex: 1; font-size: 14.5px; color: var(--text-1); }
  .chev { color: var(--text-3); font-size: 18px; }

  /* Indent by the guideline's own numbering, so 4.1.3.2 sits under 4.1.3. */
  .depth-2 { padding-left: 30px; }
  .depth-3 { padding-left: 44px; }
  .depth-4 { padding-left: 58px; }
  .depth-2 .row-title, .depth-3 .row-title, .depth-4 .row-title {
    font-size: 13.5px;
    color: var(--text-2);
  }

  .hit { flex-direction: column; align-items: flex-start; gap: 4px; }
  .hit-title { font-size: 13px; color: var(--accent-h); }
  .hit-snippet { font-size: 13.5px; color: var(--text-2); line-height: 1.45; }

  .reader-bar {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    padding: 8px 12px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
  }
  .back { color: var(--accent-h); font-size: 15px; padding: 8px; min-height: 44px; }
  .nav { display: flex; gap: 6px; }
  .nav button {
    font-size: 13px;
    color: var(--text-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 0 12px;
    min-height: 40px;
  }
  .nav button:disabled { color: var(--text-3); opacity: .45; }

  .reader {
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding: 18px 18px calc(32px + env(safe-area-inset-bottom));
    /* Guideline prose is read, not skimmed — allow selection here. */
    user-select: text;
    -webkit-user-select: text;
  }
  .section-title { font-size: 20px; line-height: 1.3; margin-bottom: 14px; color: var(--text-1); }

  .prose { font-family: var(--serif); font-size: 16.5px; line-height: 1.65; color: var(--text-1); }
  .prose :global(p) { margin-bottom: 14px; }
  .prose :global(strong) { color: var(--text-1); }
  .prose :global(em) { color: var(--text-2); }
  .prose :global(sup.cite) {
    font-family: -apple-system, sans-serif;
    font-size: 10.5px;
    color: var(--accent-h);
    padding: 0 2px;
  }
  .prose :global(.md-table-wrap) {
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    margin: 0 0 16px;
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .prose :global(.md-table) {
    border-collapse: collapse;
    width: 100%;
    font-family: -apple-system, sans-serif;
    font-size: 13px;
  }
  .prose :global(.md-table td) {
    border-bottom: 1px solid var(--border);
    padding: 8px 10px;
    vertical-align: top;
    line-height: 1.45;
  }

  .empty, .err { padding: 40px 20px; text-align: center; color: var(--text-3); font-size: 14px; }
  .err { color: #d6897b; }
</style>
