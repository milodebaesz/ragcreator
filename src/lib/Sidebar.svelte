<script>
  import { invoke } from '@tauri-apps/api/core'
  import { config, activeProject, activeTab, projectNames } from './stores.js'

  let showNewModal = false
  let newName = ''
  let newYear = ''
  let creating = false
  let createError = ''

  async function selectProject(name) {
    try {
      const cfg = await invoke('set_active_project', { name })
      config.set(cfg)
      activeProject.set(name)
      activeTab.set('pipeline')
    } catch (e) {
      console.error(e)
    }
  }

  async function createProject() {
    if (!newName.trim()) { createError = 'Naam is verplicht'; return }
    creating = true
    createError = ''
    try {
      const cfg = await invoke('create_project', {
        name: newName.trim(),
        year: newYear.trim(),
      })
      config.set(cfg)
      activeProject.set(cfg.active)
      activeTab.set('pipeline')
      showNewModal = false
      newName = ''
      newYear = ''
    } catch (e) {
      createError = String(e)
    } finally {
      creating = false
    }
  }

  async function deleteProject(name) {
    if (!confirm(`Project "${name}" verwijderen? De data-map blijft bewaard.`)) return
    try {
      const cfg = await invoke('delete_project', { name })
      config.set(cfg)
      activeProject.set(cfg.active || null)
    } catch (e) {
      console.error(e)
    }
  }

  function getInitials(name) {
    return name.slice(0, 2).toUpperCase()
  }

  function getYear(name) {
    return $config?.project_meta?.[name]?.year ?? ''
  }
</script>

<!-- Sidebar -->
<aside class="sidebar">
  <header class="brand">
    <svg class="logo" viewBox="0 0 32 32" fill="none">
      <circle cx="16" cy="16" r="15" stroke="var(--accent)" stroke-width="1.4"/>
      <path d="M11 21V11h4.2c1.9 0 3.3 1.2 3.3 2.9 0 1.3-.8 2.3-2 2.7l2.5 4.4h-1.9l-2.3-4.1h-2.1V21H11Zm1.7-5.6h2.4c1 0 1.7-.6 1.7-1.5s-.7-1.5-1.7-1.5h-2.4v3Z" fill="var(--accent)"/>
    </svg>
    <div>
      <div class="brand-name serif">RAGCreator</div>
      <div class="brand-sub">Medische richtlijnen</div>
    </div>
  </header>

  <div class="section-label">Projecten</div>

  <nav class="project-list">
    {#each $projectNames as name}
      <!-- svelte-ignore a11y-click-events-have-key-events -->
      <div
        class="project-item"
        class:active={$activeProject === name}
        on:click={() => selectProject(name)}
        role="button"
        tabindex="0"
        on:keydown={e => e.key === 'Enter' && selectProject(name)}
      >
        <div class="project-avatar">{getInitials(name)}</div>
        <div class="project-info">
          <span class="project-name">{name}</span>
          {#if getYear(name)}
            <span class="project-year">{getYear(name)}</span>
          {/if}
        </div>
        <!-- svelte-ignore a11y-click-events-have-key-events -->
        <button
          class="delete-btn"
          title="Verwijder project"
          on:click|stopPropagation={() => deleteProject(name)}
        >✕</button>
      </div>
    {/each}

    {#if $projectNames.length === 0}
      <p class="no-projects">Geen projecten</p>
    {/if}
  </nav>

  <button class="new-btn" on:click={() => showNewModal = true}>
    <span class="plus">+</span> Nieuw project
  </button>
</aside>

<!-- New project modal -->
{#if showNewModal}
  <!-- svelte-ignore a11y-click-events-have-key-events -->
  <div class="overlay" on:click={() => showNewModal = false} role="dialog" aria-modal="true">
    <!-- svelte-ignore a11y-click-events-have-key-events -->
    <div class="modal" on:click|stopPropagation>
      <h2 class="modal-title serif">Nieuw project</h2>

      <label class="field">
        <span class="field-label">Naam <span class="required">*</span></span>
        <input
          bind:value={newName}
          placeholder="bijv. ACS_2023"
          on:keydown={e => e.key === 'Enter' && createProject()}
          autofocus
        />
      </label>

      <label class="field">
        <span class="field-label">Jaar</span>
        <input
          bind:value={newYear}
          placeholder="bijv. 2024"
          on:keydown={e => e.key === 'Enter' && createProject()}
        />
      </label>

      {#if createError}
        <p class="modal-error">{createError}</p>
      {/if}

      <div class="modal-actions">
        <button class="btn-ghost" on:click={() => showNewModal = false}>Annuleren</button>
        <button class="btn-primary" on:click={createProject} disabled={creating}>
          {creating ? 'Aanmaken…' : 'Aanmaken'}
        </button>
      </div>
    </div>
  </div>
{/if}

<style>
  .sidebar {
    width: 220px;
    min-width: 220px;
    background: var(--bg-surface);
    border-right: 1px solid var(--border);
    display: flex;
    flex-direction: column;
    padding: 0 0 16px;
    overflow: hidden;
  }

  .brand {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 20px 16px 18px;
    border-bottom: 1px solid var(--border);
  }
  .logo { width: 30px; height: 30px; flex-shrink: 0; }
  .brand-name { font-weight: 600; font-size: 15px; }
  .brand-sub  { font-size: 11px; color: var(--text-3); }

  .section-label {
    padding: 20px 16px 8px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: .1em;
    text-transform: uppercase;
    color: var(--text-3);
  }

  .project-list {
    flex: 1;
    overflow-y: auto;
    padding: 0 8px;
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .project-item {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 8px 10px;
    border-radius: var(--radius);
    border-left: 2px solid transparent;
    cursor: pointer;
    transition: background .12s, border-color .12s;
    position: relative;
  }
  .project-item:hover          { background: var(--bg-hover); }
  .project-item.active         { background: var(--bg-hover); border-left-color: var(--accent); }
  .project-item:hover .delete-btn { opacity: 1; }

  .project-avatar {
    width: 26px; height: 26px; flex-shrink: 0;
    font-family: var(--mono);
    display: flex; align-items: center; justify-content: center;
    font-size: 10px; font-weight: 700; color: var(--text-3);
    border: 1px solid var(--border);
  }
  .project-item.active .project-avatar {
    color: var(--accent-h);
    border-color: var(--accent);
  }

  .project-info {
    display: flex;
    flex-direction: column;
    min-width: 0;
    flex: 1;
  }
  .project-name {
    font-size: 13px;
    font-weight: 500;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .project-year {
    font-size: 11px;
    color: var(--text-3);
  }
  .project-item.active .project-name { color: var(--accent-h); }

  .delete-btn {
    opacity: 0;
    transition: opacity .12s;
    padding: 2px 5px;
    border-radius: 4px;
    font-size: 11px;
    color: var(--text-3);
  }
  .delete-btn:hover { color: var(--error); background: var(--error-dim); }

  .no-projects {
    padding: 12px 8px;
    font-size: 12px;
    color: var(--text-3);
  }

  .new-btn {
    margin: 12px 8px 0;
    padding: 9px 12px;
    border-radius: var(--radius);
    background: transparent;
    color: var(--text-2);
    border: 1px solid var(--border);
    font-size: 12.5px;
    font-weight: 600;
    letter-spacing: .02em;
    display: flex;
    align-items: center;
    gap: 7px;
    transition: background .15s, color .15s, border-color .15s;
  }
  .new-btn:hover { background: var(--accent-dim); color: var(--accent-h); border-color: var(--accent); }
  .plus { font-size: 15px; line-height: 1; color: var(--accent); }

  /* Modal */
  .overlay {
    position: fixed; inset: 0;
    background: rgba(0,0,0,.6);
    display: flex; align-items: center; justify-content: center;
    z-index: 100;
  }
  .modal {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-top: 2px solid var(--accent);
    border-radius: var(--radius-lg);
    padding: 28px;
    width: 380px;
    box-shadow: var(--shadow);
    display: flex; flex-direction: column; gap: 16px;
  }
  .modal-title { font-size: 19px; font-weight: 500; }

  .field { display: flex; flex-direction: column; gap: 6px; }
  .field-label { font-size: 12px; color: var(--text-2); font-weight: 500; }
  .required { color: var(--error); }
  .field input { width: 100%; }

  .modal-error {
    font-size: 12px;
    color: #d6897b;
    background: var(--error-dim);
    padding: 8px 12px;
    border-radius: var(--radius);
  }

  .modal-actions {
    display: flex; justify-content: flex-end; gap: 10px; margin-top: 4px;
  }
  .btn-ghost {
    padding: 8px 16px;
    border-radius: var(--radius);
    color: var(--text-2);
    transition: background .12s;
  }
  .btn-ghost:hover { background: var(--bg-hover); color: var(--text-1); }
  .btn-primary {
    padding: 8px 20px;
    border-radius: var(--radius);
    background: var(--accent);
    color: #fff;
    font-weight: 600;
    transition: background .12s, opacity .12s;
  }
  .btn-primary:hover    { background: var(--accent-h); }
  .btn-primary:disabled { opacity: .5; cursor: not-allowed; }
</style>
