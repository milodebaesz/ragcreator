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
  <h2 class="settings-title">Instellingen</h2>

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
            <button type="button" class="toggle-vis" on:click={() => showKey = !showKey}>
              {showKey ? '🙈' : '👁'}
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
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 20px;
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .section-heading {
    font-size: 14px;
    font-weight: 600;
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
  .field input     { width: 100%; background: var(--bg-surface); }

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
  .err-msg  { font-size: 12px; color: #fca5a5; flex: 1; }
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
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .info-title { font-size: 12px; font-weight: 600; color: var(--text-2); }
  .info-text  { font-size: 12px; color: var(--text-3); line-height: 1.6; }
  .info-text code {
    font-family: var(--mono);
    background: var(--bg-hover);
    padding: 1px 5px;
    border-radius: 3px;
    color: var(--accent-h);
  }
</style>
