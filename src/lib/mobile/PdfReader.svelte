<script>
  // The guideline PDF, rendered in the app with PDF.js.
  //
  // Pages are placeholders until they scroll near the viewport, and their
  // canvases are released again once they are far away. iOS caps the memory
  // all canvases together may use; rendering a 150-page guideline up front
  // would blow through it and leave blank pages.
  import { onDestroy, tick, createEventDispatcher } from 'svelte'
  import { loadPdf, rememberPage } from './pdf.js'

  export let project
  /** 1-based page to show; changing it jumps there. */
  export let page = 1
  /** Show a close button (when opened over the app from a recommendation). */
  export let closable = false

  const dispatch = createEventDispatcher()
  const ZOOMS = [1, 1.5, 2, 3]

  let doc = null
  let numPages = 0
  let ratio = 1.414 // height / width, from page 1 until a page reports its own
  let loading = true
  let err = ''
  let current = 1
  let zoomIndex = 0
  let scroller
  let pageEls = []
  let observer
  let jumpInput = ''

  /** page number → { task, canvas, cancelled } */
  const rendered = new Map()

  $: zoom = ZOOMS[zoomIndex]
  $: open(project)
  $: if (doc) jumpTo(page)

  async function open(name) {
    releaseAll()
    doc = null
    numPages = 0
    loading = true
    err = ''
    try {
      const loaded = await loadPdf(name)
      if (name !== project) return // switched away while loading
      const first = await loaded.getPage(1)
      const vp = first.getViewport({ scale: 1 })
      ratio = vp.height / vp.width
      numPages = loaded.numPages
      doc = loaded
    } catch (e) {
      err = String(e?.message ?? e)
    } finally {
      loading = false
    }
  }

  async function jumpTo(n) {
    await tick()
    observe()
    const target = Math.min(Math.max(1, n || 1), numPages)
    const el = pageEls[target - 1]
    if (el && scroller) scroller.scrollTop = el.offsetTop - 8
    current = target
  }

  function observe() {
    observer?.disconnect()
    if (!scroller) return
    // Re-observing fires the callback for every page once, which is what
    // re-renders the visible ones after a zoom change.
    observer = new IntersectionObserver(onIntersect, {
      root: scroller,
      rootMargin: '150% 0px',
    })
    pageEls.forEach(el => el && observer.observe(el))
  }

  function onIntersect(entries) {
    for (const entry of entries) {
      const n = Number(entry.target.dataset.page)
      if (entry.isIntersecting) renderPage(n, entry.target)
      else releasePage(n)
    }
  }

  async function renderPage(n, el) {
    if (!doc || rendered.has(n)) return
    const entry = { cancelled: false, task: null, canvas: null }
    rendered.set(n, entry)
    try {
      const pdfPage = await doc.getPage(n)
      if (entry.cancelled) return
      const base = pdfPage.getViewport({ scale: 1 })
      el.style.aspectRatio = `${base.width} / ${base.height}`

      // Sharp on a Retina screen without doubling memory again at 3x.
      const dpr = Math.min(window.devicePixelRatio || 1, 2)
      const viewport = pdfPage.getViewport({ scale: (el.clientWidth / base.width) * dpr })
      const canvas = document.createElement('canvas')
      canvas.width = Math.floor(viewport.width)
      canvas.height = Math.floor(viewport.height)

      entry.task = pdfPage.render({ canvasContext: canvas.getContext('2d'), viewport })
      await entry.task.promise
      if (entry.cancelled) {
        canvas.width = 0
        return
      }
      entry.canvas = canvas
      el.appendChild(canvas)
    } catch {
      // Cancelled renders reject; a real failure leaves the placeholder.
      rendered.delete(n)
    }
  }

  function releasePage(n) {
    const entry = rendered.get(n)
    if (!entry) return
    entry.cancelled = true
    entry.task?.cancel()
    if (entry.canvas) {
      // Zero-sizing hands the backing store back right away; removing the
      // element alone leaves it to the garbage collector.
      entry.canvas.width = 0
      entry.canvas.height = 0
      entry.canvas.remove()
    }
    rendered.delete(n)
  }

  function releaseAll() {
    observer?.disconnect()
    for (const n of [...rendered.keys()]) releasePage(n)
  }

  let scrollTimer
  function onScroll() {
    // The page whose top edge has passed a third of the screen is "current".
    const mark = scroller.scrollTop + scroller.clientHeight / 3
    let n = 1
    for (let i = 0; i < pageEls.length; i++) {
      if (pageEls[i] && pageEls[i].offsetTop <= mark) n = i + 1
      else break
    }
    current = n
    clearTimeout(scrollTimer)
    scrollTimer = setTimeout(() => rememberPage(project, current), 400)
  }

  async function setZoom(index) {
    if (index < 0 || index >= ZOOMS.length) return
    const keep = current
    zoomIndex = index
    releaseAll()
    await tick()
    jumpTo(keep)
  }

  function submitJump() {
    const n = parseInt(jumpInput, 10)
    jumpInput = ''
    if (n) jumpTo(n)
    document.activeElement?.blur()
  }

  onDestroy(() => {
    releaseAll()
    clearTimeout(scrollTimer)
  })
</script>

<div class="reader" class:overlay={closable}>
  <div class="bar">
    {#if closable}
      <button class="close" on:click={() => dispatch('close')}>Sluit</button>
    {/if}
    <form class="pager" on:submit|preventDefault={submitJump}>
      <input
        class="page-input"
        type="number"
        inputmode="numeric"
        min="1"
        max={numPages}
        placeholder={String(current)}
        bind:value={jumpInput}
        aria-label="Ga naar pagina"
      />
      <span class="of">/ {numPages || '–'}</span>
    </form>
    <div class="zoom">
      <button disabled={zoomIndex === 0} on:click={() => setZoom(zoomIndex - 1)} aria-label="Uitzoomen">−</button>
      <span class="zoom-level">{Math.round(zoom * 100)}%</span>
      <button disabled={zoomIndex === ZOOMS.length - 1} on:click={() => setZoom(zoomIndex + 1)} aria-label="Inzoomen">+</button>
    </div>
  </div>

  <div class="pages" bind:this={scroller} on:scroll={onScroll}>
    {#if err}
      <p class="msg err">{err}</p>
    {:else if loading}
      <p class="msg">PDF laden…</p>
    {:else}
      <div class="stack" style="width: {zoom * 100}%">
        {#each Array(numPages) as _, i (i)}
          <div
            class="page"
            data-page={i + 1}
            bind:this={pageEls[i]}
            style="aspect-ratio: 1 / {ratio}"
          >
            <span class="page-num">{i + 1}</span>
          </div>
        {/each}
      </div>
    {/if}
  </div>
</div>

<style>
  .reader {
    display: flex;
    flex-direction: column;
    height: 100%;
    background: var(--bg-base);
  }
  .reader.overlay { padding-top: env(safe-area-inset-top); }

  .bar {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 12px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
  }
  .close {
    color: var(--accent-h);
    font-size: 15px;
    font-weight: 600;
    padding: 0 6px;
    min-height: 44px;
  }

  .pager { display: flex; align-items: center; gap: 6px; flex: 1; }
  .page-input {
    width: 64px;
    min-height: 38px;
    padding: 6px 8px;
    text-align: center;
    font-size: 16px; /* below 16px iOS zooms the page on focus */
  }
  .page-input::placeholder { color: var(--text-1); }
  .of { font-size: 13px; color: var(--text-3); }

  .zoom { display: flex; align-items: center; gap: 4px; }
  .zoom button {
    width: 40px;
    min-height: 38px;
    font-size: 20px;
    color: var(--text-2);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .zoom button:disabled { opacity: .35; }
  .zoom-level { font-size: 12px; color: var(--text-3); min-width: 40px; text-align: center; }

  .pages {
    /* Positioned so each page's offsetTop is measured from here — the jump
       and current-page logic both scroll by it. */
    position: relative;
    flex: 1;
    overflow: auto;
    -webkit-overflow-scrolling: touch;
    padding: 8px 8px calc(24px + env(safe-area-inset-bottom));
  }
  .stack { display: flex; flex-direction: column; gap: 8px; min-width: 100%; }

  .page {
    position: relative;
    width: 100%;
    background: #fff;
    border-radius: 2px;
    overflow: hidden;
  }
  .page :global(canvas) {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
  }
  .page-num {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    font-size: 13px;
    color: #999;
  }

  .msg { padding: 40px 20px; text-align: center; color: var(--text-3); font-size: 14px; }
  .msg.err { color: #d6897b; }
</style>
