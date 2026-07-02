<script>
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import { listen } from '@tauri-apps/api/event'

  import Sidebar   from './lib/Sidebar.svelte'
  import Pipeline  from './lib/Pipeline.svelte'
  import Results   from './lib/Results.svelte'
  import Search    from './lib/Search.svelte'
  import Settings  from './lib/Settings.svelte'

  import {
    config, activeProject, activeTab, envConfig, projectStatus,
    appendStepLog, setStepState,
  } from './lib/stores.js'

  let error = null

  onMount(async () => {
    try {
      // Load config
      const cfg = await invoke('get_config')
      config.set(cfg)
      if (cfg.active) activeProject.set(cfg.active)

      // Load env config
      const env = await invoke('get_env_config')
      envConfig.set(env)
    } catch (e) {
      error = String(e)
    }

    // Global pipeline event listeners
    await listen('pipeline-log', ({ payload }) => {
      appendStepLog(payload.step, payload.line, payload.is_stderr)
    })

    await listen('pipeline-done', ({ payload }) => {
      setStepState(payload.step, payload.success ? 'done' : 'error')
      // Status can only change once the step process has actually exited —
      // refresh here instead of guessing with a timeout.
      if ($activeProject) refreshStatus($activeProject)
    })
  })

  // Refresh project status whenever active project changes
  $: if ($activeProject) refreshStatus($activeProject)

  async function refreshStatus(project) {
    try {
      const status = await invoke('get_project_status', { project })
      projectStatus.set(status)
    } catch (_) {}
  }
</script>

<div class="app">
  <Sidebar />

  <main class="main">
    {#if error}
      <div class="startup-error">
        <span class="icon">⚠</span>
        Opstartfout: {error}
      </div>
    {:else if !$activeProject}
      <div class="empty-state">
        <div class="empty-mark">RC</div>
        <p>Maak een project aan of selecteer er één via de zijbalk.</p>
      </div>
    {:else}
      <!-- Tab bar -->
      <nav class="tabbar">
        {#each [
          { id:'pipeline', label:'Pipeline' },
          { id:'results',  label:'Resultaten' },
          { id:'search',   label:'Zoeken' },
          { id:'settings', label:'Instellingen' },
        ] as tab}
          <button
            class="tab"
            class:active={$activeTab === tab.id}
            on:click={() => activeTab.set(tab.id)}
          >{tab.label}</button>
        {/each}
      </nav>

      <!-- Tab content -->
      <div class="tab-content">
        {#if $activeTab === 'pipeline'}
          <Pipeline />
        {:else if $activeTab === 'results'}
          <Results />
        {:else if $activeTab === 'search'}
          <Search />
        {:else if $activeTab === 'settings'}
          <Settings />
        {/if}
      </div>
    {/if}
  </main>
</div>

<style>
  :global(*, *::before, *::after) { box-sizing: border-box; margin: 0; padding: 0; }

  :global(:root) {
    --bg-base:     #16141a;
    --bg-surface:  #1c1a21;
    --bg-card:     #221f28;
    --bg-hover:    #2b2732;
    --border:      #363140;
    --accent:      #c9903f;
    --accent-h:    #ddab63;
    --accent-dim:  rgba(201,144,63,.16);
    --success:     #5c9d76;
    --success-dim: rgba(92,157,118,.16);
    --error:       #c8604e;
    --error-dim:   rgba(200,96,78,.16);
    --warn:        #c9903f;
    --warn-dim:    rgba(201,144,63,.16);
    --text-1:      #eae5dd;
    --text-2:      #a49dab;
    --text-3:      #665f70;
    --mono:        'JetBrains Mono','Fira Code','Cascadia Code',monospace;
    --serif:       'Iowan Old Style','Palatino','Georgia',serif;
    --radius:      5px;
    --radius-lg:   8px;
    --shadow:      0 12px 32px rgba(0,0,0,.5);
  }

  :global(body) {
    background: var(--bg-base);
    color: var(--text-1);
    font-family: -apple-system, BlinkMacSystemFont, 'Inter', 'Segoe UI', sans-serif;
    font-size: 14px;
    line-height: 1.5;
    overflow: hidden;
    user-select: none;
  }

  :global(h1, h2, h3, .serif) {
    font-family: var(--serif);
    letter-spacing: .01em;
  }

  :global(button) {
    cursor: pointer;
    border: none;
    background: none;
    font: inherit;
    color: inherit;
  }

  :global(input, textarea) {
    font: inherit;
    color: var(--text-1);
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 8px 12px;
    outline: none;
    transition: border-color .15s;
  }
  :global(input:focus, textarea:focus) { border-color: var(--accent); }

  :global(::-webkit-scrollbar)       { width: 6px; height: 6px; }
  :global(::-webkit-scrollbar-track) { background: transparent; }
  :global(::-webkit-scrollbar-thumb) { background: var(--border); border-radius: 3px; }

  /* Layout */
  .app {
    display: flex;
    height: 100vh;
    overflow: hidden;
  }

  .main {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow: hidden;
  }

  /* Tab bar */
  .tabbar {
    display: flex;
    gap: 28px;
    padding: 18px 28px 0;
    border-bottom: 1px solid var(--border);
    background: var(--bg-surface);
    flex-shrink: 0;
  }

  .tab {
    padding: 0 0 12px;
    color: var(--text-3);
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: .04em;
    text-transform: uppercase;
    transition: color .15s;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  .tab:hover  { color: var(--text-2); }
  .tab.active { color: var(--accent-h); border-bottom-color: var(--accent); }

  .tab-content {
    flex: 1;
    overflow: hidden;
    background: var(--bg-base);
  }

  /* Error / empty states */
  .startup-error {
    margin: 40px;
    padding: 16px 20px;
    background: var(--error-dim);
    border: 1px solid var(--error);
    border-radius: var(--radius);
    color: #d6897b;
    display: flex;
    gap: 10px;
    align-items: center;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100%;
    gap: 18px;
    color: var(--text-3);
  }
  .empty-mark {
    font-family: var(--serif);
    font-size: 34px;
    font-weight: 500;
    color: var(--text-3);
    border: 1px solid var(--border);
    border-radius: 50%;
    width: 76px;
    height: 76px;
    display: flex;
    align-items: center;
    justify-content: center;
  }
</style>
