<script>
  // Pushing projects to iCloud Drive for the iOS app to read.
  //
  // The desktop side of the bridge described in src-tauri/src/sync.rs: it
  // copies the viewer's files into the app's iCloud container, from where iOS
  // picks them up. Nothing here changes the projects themselves.
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import { config } from './stores.js'

  let status = null
  let selected = new Set()
  let includePdf = true
  let syncing = false
  let report = null
  let errMsg = ''

  $: projects = $config?.projects ?? []

  onMount(refreshStatus)

  async function refreshStatus() {
    try {
      status = await invoke('get_icloud_status')
    } catch (e) {
      errMsg = String(e)
    }
  }

  // Everything is selected by default: syncing one guideline and not the rest
  // is the unusual case, and unchanged files are skipped anyway.
  $: if (projects.length && selected.size === 0 && !report) {
    selected = new Set(projects)
  }

  function toggle(name) {
    const next = new Set(selected)
    next.has(name) ? next.delete(name) : next.add(name)
    selected = next
  }

  async function sync() {
    syncing = true
    errMsg = ''
    report = null
    try {
      report = await invoke('sync_to_icloud', {
        projects: [...selected],
        includePdf,
      })
      await refreshStatus()
    } catch (e) {
      errMsg = String(e)
    } finally {
      syncing = false
    }
  }

  function mb(bytes) {
    if (!bytes) return '0 MB'
    return (bytes / 1024 / 1024).toFixed(1) + ' MB'
  }
</script>

<section class="icloud">
  <h3 class="section-heading">
    <span class="section-dot icloud-dot"></span>
    iCloud &amp; iOS-app
  </h3>
  <p class="section-desc">
    Kopieert aanbevelingen, richtlijntekst en paginanummers naar de iCloud-map van
    RAGCreator. De iOS-app leest daaruit; de pijplijn zelf blijft op deze Mac.
  </p>

  {#if status && !status.available}
    <p class="err-msg">{status.error}</p>
  {:else if status}
    <div class="target">
      <span class="target-label">Doelmap</span>
      <code class="target-path">{status.target}</code>
    </div>

    <div class="projects">
      {#each projects as name}
        <label class="project-row">
          <input type="checkbox" checked={selected.has(name)} on:change={() => toggle(name)} />
          <span class="project-name">{name}</span>
          {#if status.synced_projects.includes(name)}
            <span class="synced">gesynchroniseerd</span>
          {/if}
        </label>
      {:else}
        <p class="section-desc">Nog geen projecten om te synchroniseren.</p>
      {/each}
    </div>

    <label class="project-row">
      <input type="checkbox" bind:checked={includePdf} />
      <span class="project-name">Bron-PDF meesturen</span>
      <span class="hint">nodig om de PDF op je iPhone te openen</span>
    </label>

    <div class="sync-row">
      <button class="btn-sync" on:click={sync} disabled={syncing || selected.size === 0}>
        {syncing ? 'Synchroniseren…' : 'Synchroniseer naar iCloud'}
      </button>
      {#if report}
        <span class="saved-msg">✓ {mb(report.bytes_copied)} gekopieerd</span>
      {/if}
    </div>

    {#if errMsg}<p class="err-msg">{errMsg}</p>{/if}

    {#if report}
      <ul class="report">
        {#each report.projects as p}
          <li>
            <span class="rep-name">{p.project}</span>
            <span class="rep-detail">
              {p.copied.length} gekopieerd · {p.skipped.length} ongewijzigd
              {#if p.missing.length}· ontbreekt: {p.missing.join(', ')}{/if}
            </span>
          </li>
        {/each}
      </ul>
    {/if}
  {/if}
</section>

<style>
  .icloud {
    border-left: 2px solid var(--border);
    padding: 2px 0 2px 18px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .section-heading {
    font-size: 13.5px;
    font-weight: 600;
    letter-spacing: .02em;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .section-dot { width: 7px; height: 7px; border-radius: 50%; }
  .icloud-dot { background: #6aa3d6; }

  .section-desc { font-size: 12.5px; color: var(--text-3); line-height: 1.55; }

  .target { display: flex; flex-direction: column; gap: 4px; }
  .target-label {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: var(--text-3);
  }
  .target-path {
    font-family: var(--mono);
    font-size: 11.5px;
    color: var(--text-2);
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 6px 8px;
    word-break: break-all;
  }

  .projects { display: flex; flex-direction: column; gap: 2px; }
  .project-row {
    display: flex;
    align-items: center;
    gap: 9px;
    font-size: 13px;
    color: var(--text-2);
    padding: 4px 0;
    cursor: pointer;
  }
  .project-row input { width: auto; padding: 0; accent-color: var(--accent); }
  .project-name { color: var(--text-1); }
  .synced, .hint { font-size: 11px; color: var(--text-3); }

  .sync-row { display: flex; align-items: center; gap: 12px; margin-top: 4px; }
  .btn-sync {
    background: var(--accent-dim);
    color: var(--accent-h);
    border: 1px solid var(--accent);
    border-radius: var(--radius);
    padding: 8px 16px;
    font-size: 13px;
    font-weight: 600;
  }
  .btn-sync:disabled { opacity: .5; cursor: default; }

  .saved-msg { font-size: 12.5px; color: var(--success); }
  .err-msg { font-size: 12.5px; color: #d6897b; line-height: 1.5; }

  .report { list-style: none; display: flex; flex-direction: column; gap: 6px; }
  .report li { display: flex; flex-direction: column; gap: 1px; }
  .rep-name { font-size: 12.5px; color: var(--text-1); }
  .rep-detail { font-size: 11.5px; color: var(--text-3); }
</style>
