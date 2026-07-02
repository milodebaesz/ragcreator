<script>
  import { invoke } from '@tauri-apps/api/core'
  import { envConfig } from './stores.js'

  let saving  = false
  let saved   = false
  let errMsg  = ''
  let showKey = false

  // Local copy for editing
  let form = { openai_key: '', mongodb_uri: '', mongodb_db: 'rag_db', mongodb_coll: 'rag_chunks' }

  // Sync with store on mount
  const unsub = envConfig.subscribe(v => {
    form = { ...v }
  })

  import { onDestroy } from 'svelte'
  onDestroy(unsub)

  async function save() {
    saving = true
    saved  = false
    errMsg = ''
    try {
      await invoke('save_env_config', { config: form })
      envConfig.set({ ...form })
      saved = true
      setTimeout(() => (saved = false), 2500)
    } catch (e) {
      errMsg = String(e)
    } finally {
      saving = false
    }
  }
</script>

<div class="settings">
  <h2 class="settings-title serif">Instellingen</h2>

  <form class="settings-form" on:submit|preventDefault={save}>

    <!-- OpenAI -->
    <section class="settings-section">
      <h3 class="section-heading">
        <span class="section-dot openai"></span>
        OpenAI
      </h3>
      <p class="section-desc">Vereist voor stap 3 (QA-paren) en stap 4 (embeddings).</p>

      <div class="field-row">
        <label class="field">
          <span class="field-label">API-sleutel</span>
          <div class="input-wrap">
            {#if showKey}
              <input bind:value={form.openai_key} placeholder="sk-…" autocomplete="off" />
            {:else}
              <input type="password" bind:value={form.openai_key} placeholder="sk-…" autocomplete="off" />
            {/if}
            <button type="button" class="toggle-vis" on:click={() => showKey = !showKey} title={showKey ? 'Verbergen' : 'Tonen'}>
              {#if showKey}
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M2 2l12 12M6.6 6.7a2 2 0 0 0 2.8 2.8M4.3 4.5C2.8 5.5 1.7 7 1.2 8c1.2 2.7 3.9 5 6.8 5 1 0 2-.3 2.9-.8M10 3.3c-.6-.2-1.3-.3-2-.3-2.9 0-5.6 2.3-6.8 5" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/></svg>
              {:else}
                <svg width="15" height="15" viewBox="0 0 16 16" fill="none"><path d="M1.2 8C2.4 5.3 5.1 3 8 3s5.6 2.3 6.8 5c-1.2 2.7-3.9 5-6.8 5s-5.6-2.3-6.8-5Z" stroke="currentColor" stroke-width="1.2"/><circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.2"/></svg>
              {/if}
            </button>
          </div>
        </label>
      </div>
    </section>

    <!-- MongoDB -->
    <section class="settings-section">
      <h3 class="section-heading">
        <span class="section-dot mongo"></span>
        MongoDB Atlas
      </h3>
      <p class="section-desc">Vereist voor stap 5 (upload). Zorg voor een vector search index op 'embedding' (3072 dim, cosine).</p>

      <div class="field-row">
        <label class="field stretch">
          <span class="field-label">Connection URI</span>
          <input bind:value={form.mongodb_uri} placeholder="mongodb+srv://user:pass@cluster.mongodb.net/" autocomplete="off" />
        </label>
      </div>

      <div class="field-row two-col">
        <label class="field">
          <span class="field-label">Database</span>
          <input bind:value={form.mongodb_db} placeholder="rag_db" />
        </label>
        <label class="field">
          <span class="field-label">Collection</span>
          <input bind:value={form.mongodb_coll} placeholder="rag_chunks" />
        </label>
      </div>
    </section>

    <!-- Save -->
    <div class="save-row">
      {#if errMsg}
        <p class="err-msg">{errMsg}</p>
      {/if}
      {#if saved}
        <span class="saved-msg">✓ Opgeslagen</span>
      {/if}
      <button type="submit" class="btn-save" disabled={saving}>
        {saving ? 'Opslaan…' : 'Opslaan'}
      </button>
    </div>
  </form>

  <!-- Info box -->
  <div class="info-box">
    <div class="info-title">Waar wordt dit opgeslagen?</div>
    <p class="info-text">
      Instellingen worden opgeslagen in <code>medical_rag_project/.env</code> in de project-map.
      Dit bestand wordt automatisch geladen bij elke stap die API-toegang vereist.
    </p>
  </div>
</div>

<style>
  .settings {
    padding: 28px;
    height: 100%;
    overflow-y: auto;
    max-width: 640px;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .settings-title { font-size: 20px; font-weight: 600; }

  .settings-form  { display: flex; flex-direction: column; gap: 24px; }

  /* Sections */
  .settings-section {
    border-left: 2px solid var(--border);
    padding: 2px 0 2px 18px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .section-heading {
    font-size: 13.5px;
    font-weight: 600;
    letter-spacing: .02em;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .section-dot {
    width: 8px; height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }
  .section-dot.openai { background: #10a37f; }
  .section-dot.mongo  { background: #00ed64; }
  .section-desc { font-size: 12px; color: var(--text-2); line-height: 1.5; }

  /* Fields */
  .field-row       { display: flex; gap: 12px; }
  .field-row.two-col .field { flex: 1; }
  .field           { display: flex; flex-direction: column; gap: 6px; }
  .field.stretch   { flex: 1; }
  .field-label     { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); }
  .field input     { width: 100%; background: var(--bg-card); }

  .input-wrap {
    position: relative;
    display: flex;
    align-items: center;
  }
  .input-wrap input  { flex: 1; padding-right: 36px; }
  .toggle-vis {
    position: absolute;
    right: 8px;
    font-size: 14px;
    padding: 2px 4px;
    border-radius: 4px;
    transition: background .12s;
  }
  .toggle-vis:hover { background: var(--bg-hover); }

  /* Save row */
  .save-row {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 14px;
  }
  .err-msg  { font-size: 12px; color: #d6897b; flex: 1; }
  .saved-msg { font-size: 13px; color: var(--success); }
  .btn-save {
    padding: 9px 24px;
    background: var(--accent);
    color: #fff;
    border-radius: var(--radius);
    font-weight: 600;
    font-size: 14px;
    transition: background .12s, opacity .12s;
  }
  .btn-save:hover    { background: var(--accent-h); }
  .btn-save:disabled { opacity: .5; cursor: not-allowed; }

  /* Info box */
  .info-box {
    border-left: 2px solid var(--border);
    padding: 2px 0 2px 18px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .info-title { font-size: 11px; font-weight: 700; letter-spacing: .06em; text-transform: uppercase; color: var(--text-3); }
  .info-text  { font-size: 12px; color: var(--text-3); line-height: 1.6; }
  .info-text code {
    font-family: var(--mono);
    background: var(--bg-hover);
    padding: 1px 5px;
    border-radius: 3px;
    color: var(--accent-h);
  }
</style>
