<script>
  // The iOS app: a read-only reader over whatever the desktop app has synced
  // into iCloud Drive. No pipeline, no editing — those commands are not even
  // registered in the mobile build (see src-tauri/src/lib.rs).
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'

  import MobileRecommendations from './lib/mobile/MobileRecommendations.svelte'
  import MobileGuideline from './lib/mobile/MobileGuideline.svelte'
  import MobileQaPairs from './lib/mobile/MobileQaPairs.svelte'
  import MobileOverview from './lib/mobile/MobileOverview.svelte'
  import MobileAsk from './lib/mobile/MobileAsk.svelte'
  import PdfReader from './lib/mobile/PdfReader.svelte'
  import { pdfView } from './lib/mobile/pdf.js'

  /** StorageInfo from `init_storage`, resolved before this component mounts. */
  export let storage

  // Icons are inline SVG paths (24×24, stroked) so the tab bar needs no icon
  // font or image assets, and follows the text colour for its active state.
  const TABS = [
    { id: 'ask',  label: 'Vraag',
      icon: 'M12 3.5l1.9 4.6 4.6 1.9-4.6 1.9L12 16.5l-1.9-4.6L5.5 10l4.6-1.9z M18.5 15.5l.8 1.9 1.9.8-1.9.8-.8 1.9-.8-1.9-1.9-.8 1.9-.8z' },
    { id: 'recs', label: 'Aanbevelingen',
      icon: 'M10 6.5h10 M10 12h10 M10 17.5h10 M3.8 6.5l1.4 1.4 2.3-2.6 M3.8 12l1.4 1.4 2.3-2.6 M3.8 17.5l1.4 1.4 2.3-2.6' },
    { id: 'text', label: 'Richtlijn',
      icon: 'M6.5 3.5h8l4 4v13h-12z M14.5 3.5v4h4 M9.5 12h6 M9.5 15.5h6' },
    { id: 'qa',   label: 'Q&A',
      icon: 'M4 5h11a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1H9l-4 3v-3H4a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1z M19 9h1a1 1 0 0 1 1 1v6a1 1 0 0 1-1 1h-1v3l-4-3h-4' },
    { id: 'info', label: 'Overzicht',
      icon: 'M5 20V11 M10 20V5 M15 20v-6 M20 20V8' },
  ]

  let meta = {}
  let projects = []
  let project = null
  let tab = 'recs'
  let pickerOpen = false
  let error = ''

  onMount(async () => {
    try {
      const cfg = await invoke('get_config')
      meta = cfg.project_meta ?? {}
      // The config is written by the desktop app at the end of a sync, so a
      // project listed there is guaranteed to have its files alongside it.
      // available_projects is the fallback for files copied in by hand.
      projects = cfg.projects?.length ? cfg.projects : storage.available_projects
      project = cfg.active && projects.includes(cfg.active) ? cfg.active : projects[0] ?? null
    } catch (e) {
      projects = storage.available_projects
      project = projects[0] ?? null
      if (!projects.length) error = String(e)
    }
  })

  function pick(name) {
    project = name
    pickerOpen = false
  }
</script>

<div class="app">
  <header class="header">
    <span class="brand">RC</span>
    <button class="project-btn" on:click={() => (pickerOpen = true)} disabled={projects.length < 2}>
      <span class="project-name">{project ?? 'RAGCreator'}</span>
      {#if project && meta[project]?.year}<span class="project-year">{meta[project].year}</span>{/if}
      {#if projects.length > 1}
        <svg class="chev" viewBox="0 0 24 24" aria-hidden="true"><path d="M7 10l5 5 5-5" /></svg>
      {/if}
    </button>
    <span class="brand-spacer"></span>
  </header>

  {#if pickerOpen}
    <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
    <div class="sheet-backdrop" on:click={() => (pickerOpen = false)}>
      <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-noninteractive-element-interactions -->
      <div class="sheet" role="dialog" aria-label="Richtlijn kiezen" on:click|stopPropagation>
        <div class="sheet-handle"></div>
        <h2 class="sheet-title">Richtlijn kiezen</h2>
        <div class="sheet-list">
          {#each projects as name}
            <button class="sheet-row" class:current={name === project} on:click={() => pick(name)}>
              <span class="sheet-name">{name}</span>
              {#if meta[name]?.year}<span class="sheet-year">{meta[name].year}</span>{/if}
              {#if name === project}
                <svg class="tick" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
              {/if}
            </button>
          {/each}
        </div>
      </div>
    </div>
  {/if}

  <main class="content">
    {#if !project}
      <div class="empty-state">
        <div class="mark">RC</div>
        <p class="empty-title">Nog geen richtlijn</p>
        <p class="empty-body">
          Open RAGCreator op je Mac: die zet zijn projecten in de iCloud-map van
          RAGCreator. Zodra iCloud klaar is met synchroniseren verschijnt de
          richtlijn hier.
        </p>
        {#if !storage.using_icloud}
          <p class="empty-body dim">
            iCloud Drive is op dit toestel niet beschikbaar. De app leest nu uit
            zijn eigen map in de Bestanden-app.
          </p>
        {/if}
        {#if error}<p class="empty-body err">{error}</p>{/if}
      </div>
    {:else if tab === 'ask'}
      <MobileAsk {project} />
    {:else if tab === 'recs'}
      <MobileRecommendations {project} />
    {:else if tab === 'text'}
      <MobileGuideline {project} />
    {:else if tab === 'qa'}
      <MobileQaPairs {project} />
    {:else}
      <MobileOverview {project} {storage} />
    {/if}
  </main>

  {#if $pdfView}
    <div class="pdf-overlay">
      <PdfReader
        project={$pdfView.project}
        page={$pdfView.page}
        closable
        on:close={() => pdfView.set(null)}
      />
    </div>
  {/if}

  <nav class="tabbar">
    <div class="tabs">
      {#each TABS as t}
        <button class="tab" class:active={tab === t.id} on:click={() => (tab = t.id)} aria-current={tab === t.id ? 'page' : undefined}>
          <span class="tab-icon">
            <svg viewBox="0 0 24 24" aria-hidden="true"><path d={t.icon} /></svg>
          </span>
          <span class="tab-label">{t.label}</span>
        </button>
      {/each}
    </div>
  </nav>
</div>

<style>
  :global(*, *::before, *::after) { box-sizing: border-box; margin: 0; padding: 0; }

  /* Same palette as the desktop app so a recommendation looks identical on
     both; the sizing and interaction rules below are the parts that differ. */
  :global(:root) {
    --bg-base:     #16141a;
    --bg-surface:  #1c1a21;
    --bg-card:     #221f28;
    --bg-hover:    #2b2732;
    --border:      #363140;
    --accent:      #c9903f;
    --accent-h:    #ddab63;
    --accent-dim:  rgba(201,144,63,.16);
    --warn:        #c9903f;
    --text-1:      #eae5dd;
    --text-2:      #a49dab;
    --text-3:      #665f70;
    --serif:       'Iowan Old Style','Palatino','Georgia',serif;
    --radius:      5px;
    --radius-lg:   8px;
  }

  :global(html) {
    /* Keeps the layout from resizing when the on-screen keyboard appears. */
    height: 100%;
  }

  :global(body) {
    background: var(--bg-base);
    color: var(--text-1);
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', sans-serif;
    font-size: 15px;
    line-height: 1.5;
    height: 100%;
    overflow: hidden;
    /* Text in the reader opts back in; everywhere else a long-press should not
       start a selection on a control. */
    user-select: none;
    -webkit-user-select: none;
    -webkit-tap-highlight-color: transparent;
    overscroll-behavior: none;
  }

  :global(button) {
    cursor: pointer;
    border: none;
    background: none;
    font: inherit;
    color: inherit;
    /* WebKit's native button appearance forces its own single-line layout and
       collapses block and flex children — which is every card and list row in
       this app. Resetting it is what makes them render at all on iOS. */
    -webkit-appearance: none;
    appearance: none;
    text-align: inherit;
  }

  :global(input, select) {
    font: inherit;
    color: var(--text-1);
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 12px;
    outline: none;
    -webkit-appearance: none;
    appearance: none;
  }
  :global(input:focus, select:focus) { border-color: var(--accent); }
  :global(select option) { color: var(--text-1); background: var(--bg-card); }

  .app {
    display: flex;
    flex-direction: column;
    height: 100vh;
    /* dvh follows the collapsing Safari-style toolbars on iOS. */
    height: 100dvh;
    overflow: hidden;
  }

  .header {
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: calc(env(safe-area-inset-top) + 6px) 14px 8px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
  }
  .brand, .brand-spacer { flex: 0 0 32px; }
  .brand {
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: var(--serif);
    font-size: 13px;
    color: var(--accent-h);
    border: 1px solid var(--border);
    border-radius: 50%;
  }
  .project-btn {
    flex: 1;
    min-width: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    min-height: 40px;
    padding: 0 14px;
    border-radius: 20px;
    background: var(--bg-card);
    border: 1px solid var(--border);
  }
  .project-btn:disabled { background: none; border-color: transparent; }
  .project-btn:not(:disabled):active { background: var(--bg-hover); }
  .project-name {
    font-family: var(--serif);
    font-size: 17px;
    color: var(--text-1);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .project-year {
    flex-shrink: 0;
    font-size: 11.5px;
    font-weight: 600;
    color: var(--text-3);
    padding: 1px 7px;
    border-radius: 10px;
    background: var(--bg-hover);
  }
  .chev, .tick, .tab-icon svg {
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .chev { flex-shrink: 0; width: 16px; height: 16px; color: var(--text-3); }

  /* Picking a guideline: a sheet from the bottom, within thumb reach, over
     the content instead of pushing it down. */
  .sheet-backdrop {
    position: fixed;
    inset: 0;
    z-index: 30;
    display: flex;
    align-items: flex-end;
    background: rgba(0, 0, 0, .55);
    animation: fade .18s ease-out;
  }
  .sheet {
    width: 100%;
    max-height: 75vh;
    display: flex;
    flex-direction: column;
    background: var(--bg-surface);
    border-top: 1px solid var(--border);
    border-radius: 18px 18px 0 0;
    padding: 8px 12px calc(14px + env(safe-area-inset-bottom));
    animation: rise .24s cubic-bezier(.2, .8, .2, 1);
  }
  .sheet-handle {
    width: 38px;
    height: 5px;
    margin: 0 auto 10px;
    border-radius: 3px;
    background: var(--border);
  }
  .sheet-title {
    font-family: inherit;
    font-size: 12px;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    color: var(--text-3);
    padding: 0 8px 8px;
  }
  .sheet-list { overflow-y: auto; display: flex; flex-direction: column; gap: 4px; }
  .sheet-row {
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    min-height: 52px;
    padding: 0 14px;
    border-radius: 12px;
    text-align: left;
  }
  .sheet-row:active { background: var(--bg-hover); }
  .sheet-row.current { background: var(--accent-dim); }
  .sheet-name { flex: 1; font-size: 16px; color: var(--text-1); }
  .sheet-row.current .sheet-name { color: var(--accent-h); }
  .sheet-year { font-size: 13px; color: var(--text-3); }
  .tick { width: 20px; height: 20px; color: var(--accent-h); }

  @keyframes fade { from { opacity: 0; } }
  @keyframes rise { from { transform: translateY(100%); } }

  .content { flex: 1; overflow: hidden; }

  /* Over everything, tab bar included: a PDF opened from a recommendation is
     a detour, and "Sluit" returns to exactly where the list was. */
  .pdf-overlay {
    position: fixed;
    inset: 0;
    z-index: 20;
  }

  /* A floating capsule rather than a full-width strip: the active tab gets a
     pill behind its icon, the way iOS and Material both mark it now. */
  .tabbar {
    flex-shrink: 0;
    padding: 6px 8px calc(env(safe-area-inset-bottom) + 4px);
    background: var(--bg-base);
  }
  .tabs {
    display: flex;
    padding: 4px 2px;
    background: var(--bg-surface);
    border: 1px solid var(--border);
    border-radius: 26px;
    box-shadow: 0 6px 24px rgba(0, 0, 0, .35);
  }
  .tab {
    /* Basis 0, not auto: every tab gets an equal share instead of one sized to
       its label. The global button reset inherits text-align, hence centre. */
    flex: 1 1 0;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 4px 0 5px;
    text-align: center;
    color: var(--text-3);
    border-radius: 20px;
    transition: color .15s;
  }
  .tab-icon {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 46px;
    height: 28px;
    border-radius: 14px;
    transition: background .2s;
  }
  .tab-icon svg { width: 22px; height: 22px; }
  .tab-label {
    /* "Aanbevelingen" is the widest and must fit one line at 390pt. */
    max-width: 100%;
    font-size: 9.5px;
    font-weight: 600;
    letter-spacing: -.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .tab.active { color: var(--accent-h); }
  .tab.active .tab-icon { background: var(--accent-dim); }
  .tab:active .tab-icon { background: var(--bg-hover); }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 14px;
    padding: 32px 28px;
    text-align: center;
  }
  .mark {
    font-family: var(--serif);
    font-size: 28px;
    color: var(--text-3);
    border: 1px solid var(--border);
    border-radius: 50%;
    width: 64px;
    height: 64px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
  .empty-title { font-family: var(--serif); font-size: 18px; color: var(--text-1); }
  .empty-body { font-size: 14px; color: var(--text-3); line-height: 1.6; }
  .empty-body.dim { font-size: 12.5px; }
  .empty-body.err { color: #d6897b; font-size: 12.5px; }
</style>
