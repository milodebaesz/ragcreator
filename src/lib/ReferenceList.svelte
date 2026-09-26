<script>
  // Clickable reference list: every citation on a recommendation becomes a
  // one-click route to the actual paper.
  import { invoke } from '@tauri-apps/api/core'
  import { parseReference, pubmedUrl, doiUrl, scholarUrl } from './references.js'

  /** @type {{id:number,text:string}[]} */
  export let references = []
  /** Numbers cited by the recommendation, used to flag ones that never resolved. */
  export let refIds = []
  export let collapsedAfter = 4

  let expanded = false
  let copiedId = null
  let openErr = ''

  $: parsed = references.map(r => ({ id: r.id, ...parseReference(r.text) }))
  $: shown = expanded ? parsed : parsed.slice(0, collapsedAfter)
  $: resolvedIds = new Set(references.map(r => r.id))
  $: missing = (refIds ?? []).filter(n => !resolvedIds.has(n))

  async function open(url) {
    if (!url) return
    openErr = ''
    try {
      await invoke('open_external', { url })
    } catch (e) {
      openErr = String(e)
    }
  }

  async function copy(ref) {
    try {
      await navigator.clipboard.writeText(ref.raw)
      copiedId = ref.id
      setTimeout(() => { if (copiedId === ref.id) copiedId = null }, 1500)
    } catch (_) {
      openErr = 'Kopiëren naar klembord is niet gelukt.'
    }
  }
</script>

{#if parsed.length > 0 || missing.length > 0}
  <div class="refs">
    <div class="refs-head">
      <span class="refs-label">Referenties</span>
      <span class="refs-count">{parsed.length}</span>
      {#if missing.length > 0}
        <span class="refs-missing" title="Deze nummers staan wel in de aanbeveling, maar zijn niet teruggevonden in de referentielijst van de richtlijn.">
          {missing.length} niet opgelost: {missing.join(', ')}
        </span>
      {/if}
    </div>

    <ul class="ref-list">
      {#each shown as ref (ref.id + ref.raw.slice(0, 20))}
        <li class="ref-item">
          <span class="ref-num">{ref.id || '·'}</span>

          <div class="ref-body">
            <button class="ref-title" on:click={() => open(pubmedUrl(ref))} title="Zoek dit artikel op PubMed">
              {ref.title ?? ref.raw}
            </button>

            <div class="ref-meta">
              {#if ref.authors}<span class="ref-authors">{ref.authors}</span>{/if}
              {#if ref.journal || ref.year}
                <span class="ref-journal">
                  {ref.journal ?? ''}{ref.year ? ` ${ref.year}` : ''}{ref.volume ? `;${ref.volume}` : ''}{ref.pages ? `:${ref.pages}` : ''}
                </span>
              {/if}
            </div>

            <div class="ref-actions">
              <button class="ref-btn primary" on:click={() => open(pubmedUrl(ref))}>PubMed</button>
              {#if ref.doi}
                <button class="ref-btn" on:click={() => open(doiUrl(ref))} title={ref.doi}>Volledige tekst</button>
              {/if}
              <button class="ref-btn" on:click={() => open(scholarUrl(ref))}>Scholar</button>
              <button class="ref-btn ghost" on:click={() => copy(ref)}>
                {copiedId === ref.id ? 'Gekopieerd' : 'Kopieer'}
              </button>
            </div>
          </div>
        </li>
      {/each}
    </ul>

    {#if parsed.length > collapsedAfter}
      <button class="ref-more" on:click={() => expanded = !expanded}>
        {expanded ? '▴ Minder tonen' : `▾ Alle ${parsed.length} referenties tonen`}
      </button>
    {/if}

    {#if openErr}<p class="ref-err">{openErr}</p>{/if}
  </div>
{/if}

<style>
  .refs { display: flex; flex-direction: column; gap: 8px; }

  .refs-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .refs-label {
    font-size: 11px; font-weight: 700; letter-spacing: .06em;
    text-transform: uppercase; color: var(--text-3);
  }
  .refs-count {
    padding: 1px 7px; border-radius: 3px;
    background: var(--bg-hover); color: var(--text-2);
    font-family: var(--mono); font-size: 10.5px; font-weight: 700;
  }
  .refs-missing {
    padding: 1px 7px; border-radius: 3px;
    background: var(--warn-dim); color: var(--warn);
    font-size: 11px; font-weight: 600;
  }

  .ref-list { list-style: none; display: flex; flex-direction: column; gap: 2px; }

  .ref-item {
    display: flex; gap: 9px; align-items: flex-start;
    padding: 7px 8px; border-radius: var(--radius);
    transition: background .12s;
  }
  .ref-item:hover { background: var(--bg-card); }

  .ref-num {
    flex-shrink: 0; min-width: 24px; margin-top: 1px;
    padding: 1px 5px; border-radius: 3px; text-align: center;
    background: var(--bg-hover); color: var(--text-3);
    font-family: var(--mono); font-size: 10.5px; font-weight: 700;
  }

  .ref-body { display: flex; flex-direction: column; gap: 3px; min-width: 0; flex: 1; }

  .ref-title {
    text-align: left; padding: 0;
    font-size: 12.5px; line-height: 1.45; font-weight: 600;
    color: var(--text-1);
    transition: color .12s;
  }
  .ref-title:hover { color: var(--accent-h); text-decoration: underline; }

  .ref-meta { display: flex; gap: 8px; flex-wrap: wrap; font-size: 11.5px; color: var(--text-3); }
  .ref-authors {
    max-width: 340px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  }
  .ref-journal { font-style: italic; }

  .ref-actions { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 3px; }
  .ref-btn {
    padding: 3px 9px; border-radius: 3px;
    border: 1px solid var(--border); color: var(--text-2);
    font-size: 11px; font-weight: 600;
    transition: background .12s, color .12s, border-color .12s;
  }
  .ref-btn:hover { background: var(--bg-hover); color: var(--text-1); border-color: var(--text-3); }
  .ref-btn.primary { border-color: var(--accent); color: var(--accent-h); }
  .ref-btn.primary:hover { background: var(--accent-dim); }
  .ref-btn.ghost { border-color: transparent; color: var(--text-3); }

  .ref-more {
    align-self: flex-start; padding: 3px 6px;
    font-size: 11.5px; font-weight: 600; color: var(--text-3);
  }
  .ref-more:hover { color: var(--accent-h); }

  .ref-err { font-size: 11.5px; color: #d6897b; }
</style>
