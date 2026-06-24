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
        <div class="empty-icon">⬡</div>
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
    --bg-base:     #0d0e1a;
    --bg-surface:  #13141f;
    --bg-card:     #1a1b2e;
    --bg-hover:    #22233a;
    --border:      #2a2c45;
    --accent:      #6366f1;
    --accent-h:    #818cf8;
    --accent-dim:  rgba(99,102,241,.15);
    --success:     #22c55e;
    --success-dim: rgba(34,197,94,.15);
    --error:       #ef4444;
    --error-dim:   rgba(239,68,68,.15);
    --warn:        #f59e0b;
    --warn-dim:    rgba(245,158,11,.15);
    --text-1:      #e2e8f0;
    --text-2:      #94a3b8;
    --text-3:      #4b5680;
    --mono:        'JetBrains Mono','Fira Code','Cascadia Code',monospace;
    --radius:      8px;
    --radius-lg:   12px;
    --shadow:      0 4px 24px rgba(0,0,0,.4);
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
    gap: 2px;
    padding: 12px 20px 0;
    border-bottom: 1px solid var(--border);
    background: var(--bg-surface);
    flex-shrink: 0;
  }

  .tab {
    padding: 8px 18px;
    border-radius: var(--radius) var(--radius) 0 0;
    color: var(--text-2);
    font-size: 13px;
    font-weight: 500;
    transition: color .15s, background .15s;
    border-bottom: 2px solid transparent;
    margin-bottom: -1px;
  }
  .tab:hover  { color: var(--text-1); background: var(--bg-hover); }
  .tab.active { color: var(--accent-h); border-bottom-color: var(--accent); background: var(--bg-card); }

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
    color: #fca5a5;
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
    gap: 16px;
    color: var(--text-3);
  }
  .empty-icon { font-size: 48px; opacity: .4; }
</style>
