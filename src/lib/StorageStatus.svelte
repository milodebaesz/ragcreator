<script>
  // Where the project data lives, and whether the iOS app can see it.
  //
  // There is nothing to press here: when the app's iCloud container exists the
  // desktop app works in it directly (see src-tauri/src/storage.rs), so the
  // iOS app sees every change as soon as iCloud has uploaded it.
  import { onMount } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'

  let storage = null
  let errMsg = ''

  onMount(async () => {
    try {
      storage = await invoke('init_storage')
    } catch (e) {
      errMsg = String(e)
    }
  })
</script>

<section class="storage">
  <h3 class="section-heading">
    <span class="section-dot" class:cloud={storage?.using_icloud}></span>
    Opslag &amp; iOS-app
  </h3>

  {#if errMsg}
    <p class="err-msg">{errMsg}</p>
  {:else if storage}
    <p class="section-desc">
      {#if storage.using_icloud}
        Alle projectdata — aanbevelingen, richtlijntekst, Q&amp;A-paren, embeddings en
        PDF's — staat in iCloud Drive (map <strong>RAGCreator</strong>). De iOS-app leest
        dezelfde bestanden; synchroniseren is niet nodig.
      {:else}
        De projectdata staat nog in de repo op deze Mac en is niet zichtbaar voor de
        iOS-app.
      {/if}
    </p>

    <div class="target">
      <span class="target-label">Datamap</span>
      <code class="target-path">{storage.root}/medical_rag_project</code>
    </div>

    {#if storage.note}
      <p class="note">{storage.note}</p>
    {/if}
    {#if storage.pending_downloads}
      <p class="note">
        iCloud is nog {storage.pending_downloads} bestand(en) aan het downloaden.
      </p>
    {/if}

    <p class="section-desc">
      Scripts, de Python-venv en <code>.env</code> (API-sleutels) blijven in de repo en
      gaan nooit naar iCloud.
    </p>
  {/if}
</section>

<style>
  .storage {
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
  .section-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--text-3); }
  .section-dot.cloud { background: #6aa3d6; }

  .section-desc { font-size: 12.5px; color: var(--text-3); line-height: 1.55; }
  .section-desc code { font-family: var(--mono); font-size: 11.5px; }

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

  .note { font-size: 12.5px; color: var(--text-2); line-height: 1.5; }
  .err-msg { font-size: 12.5px; color: #d6897b; line-height: 1.5; }
</style>
