<script>
  // The Richtlijn tab's numbers, sized for a phone: what this guideline
  // contains and how solid its evidence base is.
  import { invoke } from '@tauri-apps/api/core'

  export let project
  export let storage = null

  let info = null
  let loading = false
  let err = ''

  $: project, load()

  async function load() {
    if (!project) return
    loading = true
    err = ''
    try {
      info = await invoke('get_guideline_info', { project })
    } catch (e) {
      err = String(e)
      info = null
    } finally {
      loading = false
    }
  }

  function pct(part, whole) {
    return whole ? Math.round((part / whole) * 100) : 0
  }

  function shortLabel(label) {
    return label.startsWith('Class ') ? label.replace('Class ', '') : label
  }
</script>

<div class="screen">
  {#if err}
    <p class="err">{err}</p>
  {:else if loading || !info}
    <p class="empty">Laden…</p>
  {:else}
    <section class="head">
      <h2 class="title serif">{info.guideline ?? info.project}</h2>
      <p class="sub">
        {#if info.year}{info.year} · {/if}{info.pdf_name ?? 'geen PDF'}
      </p>
    </section>

    <section class="tiles">
      <div class="tile">
        <span class="tile-num">{info.recommendation_count}</span>
        <span class="tile-label">Aanbevelingen</span>
      </div>
      <div class="tile">
        <span class="tile-num">{info.table_count}</span>
        <span class="tile-label">Tabellen</span>
      </div>
      <div class="tile">
        <span class="tile-num">{info.evidence_a_count}</span>
        <span class="tile-label">Niveau A</span>
      </div>
      <div class="tile">
        <span class="tile-num">{info.approved_count}</span>
        <span class="tile-label">Geaccordeerd</span>
      </div>
    </section>

    {#if info.class_counts.length}
      <section class="block">
        <h3 class="block-title">Aanbevelingsklasse</h3>
        {#each info.class_counts as entry}
          <div class="bar-row">
            <span class="bar-label">{shortLabel(entry.label)}</span>
            <div class="bar-track">
              <div class="bar-fill" style="width: {pct(entry.count, info.recommendation_count)}%"></div>
            </div>
            <span class="bar-num">{entry.count}</span>
          </div>
        {/each}
      </section>
    {/if}

    {#if info.evidence_counts.length}
      <section class="block">
        <h3 class="block-title">Bewijsniveau</h3>
        {#each info.evidence_counts as entry}
          <div class="bar-row">
            <span class="bar-label">{entry.label}</span>
            <div class="bar-track">
              <div class="bar-fill" style="width: {pct(entry.count, info.recommendation_count)}%"></div>
            </div>
            <span class="bar-num">{entry.count}</span>
          </div>
        {/each}
      </section>
    {/if}

    <section class="block">
      <h3 class="block-title">Referenties</h3>
      <div class="fact"><span>Geciteerd</span><span>{info.cited_reference_count}</span></div>
      <div class="fact"><span>In referentielijst</span><span>{info.guideline_reference_count}</span></div>
      <div class="fact" class:warn={info.unresolved_reference_count > 0}>
        <span>Niet opgelost</span><span>{info.unresolved_reference_count}</span>
      </div>
      <div class="fact" class:warn={info.unreferenced_recommendation_count > 0}>
        <span>Zonder referentie</span><span>{info.unreferenced_recommendation_count}</span>
      </div>
    </section>

    {#if info.tables.length}
      <section class="block">
        <h3 class="block-title">Aanbevelingstabellen</h3>
        {#each info.tables as table}
          <div class="table-row">
            <span class="table-title">{table.title}</span>
            <span class="table-num">{table.recommendation_count}</span>
          </div>
        {/each}
      </section>
    {/if}

    {#if storage}
      <section class="block">
        <h3 class="block-title">Synchronisatie</h3>
        <div class="fact">
          <span>Bron</span>
          <span>{storage.using_icloud ? 'iCloud Drive' : 'Lokaal (Bestanden)'}</span>
        </div>
        {#if !storage.using_icloud}
          <p class="hint">
            iCloud is niet beschikbaar. Zet iCloud Drive aan, of zet de projectmappen
            zelf in de RAGCreator-map via de Bestanden-app.
          </p>
        {/if}
      </section>
    {/if}
  {/if}
</div>

<style>
  .screen {
    height: 100%;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding: 18px 16px calc(28px + env(safe-area-inset-bottom));
  }

  .head { margin-bottom: 18px; }
  .title { font-size: 20px; line-height: 1.3; color: var(--text-1); }
  .sub { font-size: 13px; color: var(--text-3); margin-top: 4px; }

  .tiles { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 22px; }
  .tile {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 14px;
  }
  .tile-num {
    display: block;
    font-family: var(--serif);
    font-size: 26px;
    color: var(--accent-h);
    line-height: 1.1;
  }
  .tile-label {
    display: block;
    margin-top: 4px;
    font-size: 11.5px;
    text-transform: uppercase;
    letter-spacing: .05em;
    color: var(--text-3);
  }

  .block { margin-bottom: 22px; }
  .block-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--text-3);
    margin-bottom: 10px;
  }

  .bar-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .bar-label { flex: 0 0 42px; font-size: 13px; color: var(--text-2); }
  .bar-track { flex: 1; height: 8px; background: var(--bg-card); border-radius: 4px; overflow: hidden; }
  .bar-fill { height: 100%; background: var(--accent); border-radius: 4px; }
  .bar-num { flex: 0 0 32px; text-align: right; font-size: 13px; color: var(--text-2); }

  .fact, .table-row {
    display: flex;
    justify-content: space-between;
    gap: 12px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
    font-size: 13.5px;
    color: var(--text-2);
  }
  .fact.warn span:last-child { color: var(--warn); font-weight: 600; }

  .table-title { flex: 1; color: var(--text-1); line-height: 1.4; }
  .table-num { color: var(--accent-h); }

  .hint { font-size: 12.5px; color: var(--text-3); line-height: 1.5; margin-top: 10px; }

  .empty, .err { padding: 48px 8px; text-align: center; color: var(--text-3); font-size: 14px; }
  .err { color: #d6897b; }
</style>
