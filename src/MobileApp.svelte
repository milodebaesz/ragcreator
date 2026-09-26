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

  /** StorageInfo from `init_storage`, resolved before this component mounts. */
  export let storage

  const TABS = [
    { id: 'recs',  label: 'Aanbevelingen' },
    { id: 'text',  label: 'Richtlijn' },
    { id: 'qa',    label: 'Q&A' },
    { id: 'info',  label: 'Overzicht' },
  ]

  let projects = []
  let project = null
  let tab = 'recs'
  let pickerOpen = false
  let error = ''

  onMount(async () => {
    try {
      const cfg = await invoke('get_config')
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
    <button class="project-btn" on:click={() => (pickerOpen = !pickerOpen)} disabled={projects.length < 2}>
      <span class="project-name">{project ?? 'RAGCreator'}</span>
      {#if projects.length > 1}<span class="caret" class:open={pickerOpen}>▾</span>{/if}
    </button>
  </header>

  {#if pickerOpen}
    <div class="picker">
      {#each projects as name}
        <button class="picker-row" class:current={name === project} on:click={() => pick(name)}>
          {name}
          {#if name === project}<span class="tick">✓</span>{/if}
        </button>
      {/each}
    </div>
  {/if}

  <main class="content">
    {#if !project}
      <div class="empty-state">
        <div class="mark">RC</div>
        <p class="empty-title">Nog geen richtlijn</p>
        <p class="empty-body">
          Open RAGCreator op je Mac en kies <strong>Synchroniseer naar iCloud</strong>
          bij Instellingen. Zodra iCloud klaar is met synchroniseren verschijnt de
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

  <nav class="tabbar">
    {#each TABS as t}
      <button class="tab" class:active={tab === t.id} on:click={() => (tab = t.id)}>
        {t.label}
      </button>
    {/each}
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
    padding-top: env(safe-area-inset-top);
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
  }
  .project-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    width: 100%;
    min-height: 48px;
    padding: 0 16px;
  }
  .project-name {
    font-family: var(--serif);
    font-size: 17px;
    color: var(--text-1);
  }
  .caret { color: var(--text-3); font-size: 12px; transition: transform .18s; }
  .caret.open { transform: rotate(180deg); }

  .picker {
    flex-shrink: 0;
    background: var(--bg-card);
    border-bottom: 1px solid var(--border);
  }
  .picker-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    width: 100%;
    min-height: 50px;
    padding: 0 20px;
    text-align: left;
    font-size: 15px;
    color: var(--text-2);
    border-bottom: 1px solid var(--border);
  }
  .picker-row.current { color: var(--accent-h); }
  .tick { color: var(--accent-h); }

  .content { flex: 1; overflow: hidden; }

  .tabbar {
    flex-shrink: 0;
    display: flex;
    background: var(--bg-surface);
    border-top: 1px solid var(--border);
    padding-bottom: env(safe-area-inset-bottom);
  }
  .tab {
    flex: 1;
    min-height: 52px;
    /* Four tabs now; "Aanbevelingen" is the widest and must still fit on one
       line at 390pt without wrapping. */
    font-size: 11.5px;
    font-weight: 600;
    letter-spacing: .01em;
    white-space: nowrap;
    color: var(--text-3);
    border-top: 2px solid transparent;
    margin-top: -1px;
  }
  .tab.active { color: var(--accent-h); border-top-color: var(--accent); }

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
