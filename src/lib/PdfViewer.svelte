<script>
  // Shows the page of the source PDF a recommendation was extracted from, with
  // the matching lines highlighted, so a reviewer can check the chunk against
  // the original without leaving the app.
  //
  // The page is found by searching the PDF text rather than by a stored page
  // number: that also works for chunks extracted before this feature existed,
  // and it survives edits to the recommendation text.
  import { createEventDispatcher, onMount, onDestroy } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import { activeProject } from './stores.js'

  export let chunk

  const dispatch = createEventDispatcher()
  const ZOOM_LEVELS = [1.5, 2, 2.5, 3]

  let view = null
  let loading = true
  let err = ''
  let zoom = 2
  let showHighlight = true
  let scrollBox
  let pendingScroll = false

  onMount(() => {
    window.addEventListener('keydown', onKey)
    locate()
  })
  onDestroy(() => window.removeEventListener('keydown', onKey))

  function onKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); dispatch('close') }
    else if (e.key === 'ArrowRight') { e.preventDefault(); go(1) }
    else if (e.key === 'ArrowLeft')  { e.preventDefault(); go(-1) }
  }

  async function request(page) {
    loading = true
    err = ''
    try {
      view = await invoke('locate_in_pdf', {
        project: $activeProject,
        chunkId: chunk.id,
        text: chunk.text,
        tableTitle: chunk.metadata?.table_title ?? null,
        page,
        zoom,
      })
      // The scroll itself waits for the image: see onImageLoad.
      pendingScroll = true
    } catch (e) {
      err = String(e)
      view = null
    } finally {
      loading = false
    }
  }

  /**
   * Land the reader on the recommendation instead of at the top of a dense
   * two-column page. Only possible once the page image has been decoded — the
   * container has no scrollable height before that.
   */
  function onImageLoad() {
    if (!pendingScroll) return
    pendingScroll = false
    if (!scrollBox || !view?.rects?.length) return
    const top = Math.min(...view.rects.map(r => r[1]))
    scrollBox.scrollTop = Math.max(0, top - scrollBox.clientHeight / 3)
  }

  const locate = () => request(null)

  function go(delta) {
    if (!view) return
    const next = view.page + delta
    if (next < 0 || next >= view.total_pages) return
    request(next)
  }

  function setZoom(z) {
    zoom = z
    request(view ? view.page : null)
  }

  async function openInViewer() {
    try {
      await invoke('open_project_pdf', { project: $activeProject })
    } catch (e) {
      err = String(e)
    }
  }
</script>

<!-- svelte-ignore a11y-click-events-have-key-events -->
<!-- svelte-ignore a11y-no-static-element-interactions -->
<div class="backdrop" on:click={() => dispatch('close')}>
  <div class="modal" on:click|stopPropagation>
    <header class="bar">
      <div class="bar-left">
        <span class="bar-title serif">Bron in PDF</span>
        {#if view}
          <span class="page-badge">pagina {view.page_label} <span class="dim">van {view.total_pages}</span></span>
          {#if view.score != null && view.score < 0.6}
            <span class="warn-badge" title="De tekst kwam maar deels overeen — controleer of dit de juiste plek is.">
              gedeeltelijke match
            </span>
          {/if}
        {/if}
      </div>

      <div class="bar-right">
        <button class="bar-btn" on:click={() => go(-1)} disabled={!view || view.page === 0} title="Vorige pagina (←)">‹</button>
        <button class="bar-btn" on:click={() => go(1)} disabled={!view || view.page >= view.total_pages - 1} title="Volgende pagina (→)">›</button>

        <select class="zoom" bind:value={zoom} on:change={() => setZoom(zoom)} title="Zoomniveau">
          {#each ZOOM_LEVELS as z}<option value={z}>{Math.round(z * 50)}%</option>{/each}
        </select>

        <button class="bar-btn wide" class:on={showHighlight} on:click={() => showHighlight = !showHighlight}>
          Markering
        </button>
        <button class="bar-btn wide" on:click={locate} title="Zoek de aanbeveling opnieuw op">Terug naar match</button>
        <button class="bar-btn wide" on:click={openInViewer}>Open PDF</button>
        <button class="bar-btn close" on:click={() => dispatch('close')} title="Sluiten (Esc)">✕</button>
      </div>
    </header>

    <div class="stage" bind:this={scrollBox}>
      {#if err}
        <div class="msg error">{err}</div>
      {:else if loading && !view}
        <div class="msg">Pagina zoeken…</div>
      {:else if view}
        <div class="page-wrap" style="width: {view.width}px">
          <img class="page-img" src="data:image/png;base64,{view.png_base64}" alt="Pagina {view.page_label} van de richtlijn" on:load={onImageLoad} />
          {#if showHighlight}
            {#each view.rects ?? [] as r}
              <div
                class="hl"
                style="left:{r[0]}px; top:{r[1]}px; width:{r[2] - r[0]}px; height:{r[3] - r[1]}px"
              ></div>
            {/each}
          {/if}
          {#if loading}<div class="page-loading">Laden…</div>{/if}
        </div>
      {/if}
    </div>

    <footer class="quote">
      <span class="quote-label">Chunk</span>
      <p class="quote-text">{chunk.text}</p>
    </footer>
  </div>
</div>

<style>
  .backdrop {
    position: fixed; inset: 0; z-index: 50;
    background: rgba(0,0,0,.66);
    display: flex; align-items: center; justify-content: center;
    padding: 24px;
  }

  .modal {
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow);
    width: min(1100px, 100%);
    height: 100%;
    display: flex; flex-direction: column;
    overflow: hidden;
  }

  .bar {
    display: flex; align-items: center; justify-content: space-between;
    gap: 12px; padding: 11px 14px;
    border-bottom: 1px solid var(--border);
    background: var(--bg-card);
    flex-shrink: 0;
  }
  .bar-left, .bar-right { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .bar-title { font-size: 15px; font-weight: 600; }

  .page-badge {
    padding: 2px 9px; border-radius: 3px;
    background: var(--accent-dim); color: var(--accent-h);
    font-family: var(--mono); font-size: 11px; font-weight: 600;
  }
  .page-badge .dim { color: var(--text-3); font-weight: 400; }
  .warn-badge {
    padding: 2px 9px; border-radius: 3px;
    background: var(--warn-dim); color: var(--warn);
    font-size: 11px; font-weight: 600;
  }

  .bar-btn {
    min-width: 30px; padding: 5px 9px;
    border: 1px solid var(--border); border-radius: var(--radius);
    color: var(--text-2); font-size: 12.5px; font-weight: 600;
    transition: background .12s, color .12s, border-color .12s;
  }
  .bar-btn:hover:not(:disabled) { background: var(--bg-hover); color: var(--text-1); }
  .bar-btn:disabled { opacity: .35; cursor: not-allowed; }
  .bar-btn.wide { font-size: 11.5px; }
  .bar-btn.on { background: var(--accent-dim); color: var(--accent-h); border-color: var(--accent); }
  .bar-btn.close:hover { background: var(--error-dim); color: #d6897b; border-color: var(--error); }

  .zoom { padding: 4px 8px; font-size: 11.5px; background: var(--bg-base); }

  .stage {
    flex: 1; overflow: auto;
    display: flex; justify-content: center;
    padding: 18px;
    background: #0f0e12;
  }

  .page-wrap { position: relative; flex-shrink: 0; height: fit-content; }
  .page-img {
    display: block; width: 100%; height: auto;
    border-radius: 3px;
    box-shadow: 0 6px 24px rgba(0,0,0,.55);
  }

  .hl {
    position: absolute;
    /* Multiply keeps the underlying text readable through the wash. */
    background: rgba(201,144,63,.42);
    mix-blend-mode: multiply;
    border-radius: 2px;
    outline: 1px solid rgba(201,144,63,.85);
    pointer-events: none;
  }

  .page-loading {
    position: absolute; top: 10px; right: 10px;
    padding: 4px 10px; border-radius: 3px;
    background: rgba(0,0,0,.7); color: var(--text-2);
    font-size: 11.5px;
  }

  .msg { margin: auto; color: var(--text-3); font-size: 13.5px; }
  .msg.error { color: #d6897b; max-width: 520px; text-align: center; }

  .quote {
    flex-shrink: 0; display: flex; gap: 10px; align-items: baseline;
    padding: 11px 16px;
    border-top: 1px solid var(--border);
    background: var(--bg-card);
    max-height: 92px; overflow: auto;
  }
  .quote-label {
    flex-shrink: 0;
    font-size: 10.5px; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; color: var(--text-3);
  }
  .quote-text { font-size: 12.5px; line-height: 1.55; color: var(--text-2); user-select: text; }
</style>
