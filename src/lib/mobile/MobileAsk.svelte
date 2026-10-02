<script>
  // Asking the guidelines a question.
  //
  // Searches only recommendations and Q&A pairs (see src-tauri/src/search.rs);
  // Apple Intelligence then writes a short answer from the best of those,
  // citing them by number. Without Apple Intelligence the screen still works
  // as a cross-guideline search, just without the written answer.
  import { onMount, tick } from 'svelte'
  import { invoke } from '@tauri-apps/api/core'
  import RecCard from './RecCard.svelte'
  import {
    KEYWORD_INSTRUCTIONS, ANSWER_INSTRUCTIONS, SOURCES_FOR_MODEL,
    parseKeywords, answerPrompt, renderAnswer,
  } from './ask.js'

  /** The project picked in the header, for the "alleen deze richtlijn" scope. */
  export let project

  const EXAMPLES = [
    'Wanneer is een statine geïndiceerd bij hartfalen?',
    'Welke antistolling bij longembolie en kanker?',
    'Mag iemand autorijden na een syncope?',
  ]

  let ai = null            // { available, reason }
  let question = ''
  let allGuidelines = true
  let phase = 'idle'       // idle | keywords | search | answer | done
  let asked = ''
  let keywords = []
  let hits = []
  let answer = ''
  let aiErr = ''
  let err = ''
  let sourceEls = []
  let run = 0

  $: busy = phase === 'keywords' || phase === 'search' || phase === 'answer'
  $: answerHtml = renderAnswer(answer, Math.min(hits.length, SOURCES_FOR_MODEL))

  onMount(async () => {
    try {
      ai = await invoke('ai_status')
    } catch (e) {
      ai = { available: false, reason: String(e) }
    }
  })

  async function ask(text = question) {
    const q = text.trim()
    if (!q || busy) return
    question = q
    document.activeElement?.blur()

    // A later question supersedes an earlier one still in flight.
    const mine = ++run
    const current = () => mine === run

    asked = q
    hits = []
    answer = ''
    aiErr = ''
    err = ''
    keywords = []

    try {
      if (ai?.available) {
        phase = 'keywords'
        try {
          const raw = await invoke('ai_generate', {
            instructions: KEYWORD_INSTRUCTIONS,
            prompt: q,
            temperature: 0,
          })
          if (!current()) return
          keywords = parseKeywords(raw)
        } catch {
          // The search still runs on the question itself.
        }
      }

      phase = 'search'
      const found = await invoke('ask_search', {
        query: q,
        keywords,
        project: allGuidelines ? null : project,
        limit: 8,
      })
      if (!current()) return
      hits = found

      if (hits.length && ai?.available) {
        phase = 'answer'
        try {
          const text = await invoke('ai_generate', {
            instructions: ANSWER_INSTRUCTIONS,
            prompt: answerPrompt(q, hits),
            temperature: 0.2,
          })
          if (!current()) return
          answer = text
        } catch (e) {
          if (current()) aiErr = String(e)
        }
      }
    } catch (e) {
      if (current()) err = String(e)
    } finally {
      if (current()) phase = 'done'
    }
  }

  async function onAnswerClick(e) {
    const btn = e.target.closest('button.cite')
    if (!btn) return
    const el = sourceEls[Number(btn.dataset.source) - 1]
    await tick()
    el?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    el?.classList.add('flash')
    setTimeout(() => el?.classList.remove('flash'), 1200)
  }

  function guidelineLabel(hit) {
    const m = hit.chunk.metadata
    return [hit.project, m.year].filter(Boolean).join(' · ')
  }
</script>

<div class="screen">
  <form class="bar" on:submit|preventDefault={() => ask()}>
    <textarea
      class="question"
      rows="2"
      bind:value={question}
      placeholder="Stel een vraag over de aanbevelingen…"
      on:keydown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); ask() } }}
    ></textarea>
    <div class="row">
      <div class="scope" role="radiogroup" aria-label="Zoeken in">
        <button type="button" class:active={allGuidelines} on:click={() => (allGuidelines = true)}>Alle richtlijnen</button>
        <button type="button" class:active={!allGuidelines} on:click={() => (allGuidelines = false)} disabled={!project}>
          Alleen {project ?? 'deze'}
        </button>
      </div>
      <button class="send" type="submit" disabled={busy || !question.trim()}>Vraag</button>
    </div>
  </form>

  <div class="results">
    {#if ai && !ai.available}
      <p class="notice">
        {ai.reason} Je krijgt wel de best passende aanbevelingen, zonder samenvattend antwoord.
      </p>
    {/if}

    {#if phase === 'idle'}
      <div class="intro">
        <p class="intro-text">
          Zoekt in de aanbevelingen en Q&amp;A-paren van je richtlijnen{#if ai?.available}, en
          Apple Intelligence vat de beste bronnen samen — op dit toestel, zonder internet{/if}.
        </p>
        {#each EXAMPLES as ex}
          <button class="example" on:click={() => ask(ex)}>{ex}</button>
        {/each}
      </div>
    {:else}
      {#if err}<p class="err">{err}</p>{/if}

      {#if ai?.available && (phase === 'keywords' || phase === 'search' || phase === 'answer' || answer || aiErr)}
        <section class="answer">
          <div class="answer-head">
            <span class="ai-mark">Apple Intelligence</span>
            {#if phase === 'keywords'}<span class="status">zoektermen bepalen…</span>{/if}
            {#if phase === 'search'}<span class="status">zoeken…</span>{/if}
            {#if phase === 'answer'}<span class="status">antwoord schrijven…</span>{/if}
          </div>
          {#if answer}
            <!-- svelte-ignore a11y-click-events-have-key-events a11y-no-static-element-interactions -->
            <div class="answer-body" on:click={onAnswerClick}>{@html answerHtml}</div>
            <p class="disclaimer">
              Samengevat uit de aanbevelingen hieronder; controleer altijd de bron voordat je ernaar handelt.
            </p>
          {:else if aiErr}
            <p class="err small">{aiErr}</p>
          {:else if phase === 'done' && !hits.length}
            <p class="status">Geen aanbevelingen gevonden.</p>
          {/if}
          {#if keywords.length}
            <p class="keywords">Gezocht op: {keywords.join(', ')}</p>
          {/if}
        </section>
      {/if}

      {#if hits.length}
        <h3 class="sources-title">Bronnen ({hits.length})</h3>
        {#each hits as hit, i (hit.project + '/' + hit.chunk.id + '/' + asked)}
          <div class="source" bind:this={sourceEls[i]}>
            <div class="source-head">
              <span class="num">{i + 1}</span>
              <span class="guideline">{guidelineLabel(hit)}</span>
              {#if ai?.available && i >= SOURCES_FOR_MODEL}<span class="extra">niet in antwoord</span>{/if}
            </div>
            {#if hit.qa}
              <p class="qa">Q&amp;A: {hit.qa.question}</p>
            {/if}
            <RecCard chunk={hit.chunk} project={hit.project} />
          </div>
        {/each}
      {:else if phase === 'done' && !err}
        <p class="empty">Geen aanbevelingen gevonden voor "{asked}". Probeer andere woorden.</p>
      {/if}
    {/if}
  </div>
</div>

<style>
  .screen { display: flex; flex-direction: column; height: 100%; overflow: hidden; }

  .bar {
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 10px 16px;
    background: var(--bg-surface);
    border-bottom: 1px solid var(--border);
  }
  .question {
    width: 100%;
    min-height: 60px;
    resize: none;
    font: inherit;
    font-size: 16px; /* below 16px iOS zooms in on focus */
    line-height: 1.4;
    color: var(--text-1);
    background: var(--bg-base);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 12px;
    outline: none;
    -webkit-appearance: none;
    user-select: text;
    -webkit-user-select: text;
  }
  .question:focus { border-color: var(--accent); }

  .row { display: flex; align-items: center; gap: 8px; }
  .scope {
    flex: 1;
    min-width: 0;
    display: flex;
    gap: 3px;
    padding: 3px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
  }
  .scope button {
    flex: 1 1 0;
    min-width: 0;
    text-align: center;
    min-height: 34px;
    padding: 0 6px;
    font-size: 12.5px;
    font-weight: 600;
    color: var(--text-3);
    border-radius: var(--radius);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .scope button.active { background: var(--accent-dim); color: var(--accent-h); }
  .scope button:disabled { opacity: .4; }
  .send {
    flex-shrink: 0;
    min-height: 42px;
    padding: 0 18px;
    font-size: 14px;
    font-weight: 700;
    color: var(--bg-base);
    background: var(--accent);
    border-radius: var(--radius);
    text-align: center;
  }
  .send:disabled { opacity: .4; }

  .results {
    flex: 1;
    overflow-y: auto;
    -webkit-overflow-scrolling: touch;
    padding: 14px 16px calc(24px + env(safe-area-inset-bottom));
    display: flex;
    flex-direction: column;
    gap: 12px;
  }

  .notice {
    flex-shrink: 0;
    font-size: 13px;
    line-height: 1.5;
    color: var(--text-2);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 12px;
  }

  .intro { display: flex; flex-direction: column; gap: 10px; }
  .intro-text { font-size: 14px; line-height: 1.55; color: var(--text-2); margin-bottom: 4px; }
  .example {
    text-align: left;
    font-size: 14px;
    color: var(--accent-h);
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 12px 14px;
    min-height: 46px;
  }

  .answer {
    flex-shrink: 0;
    background: var(--bg-card);
    border: 1px solid var(--accent);
    border-radius: var(--radius-lg);
    padding: 14px 16px;
  }
  .answer-head { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
  .ai-mark {
    font-size: 11px;
    font-weight: 700;
    letter-spacing: .06em;
    text-transform: uppercase;
    color: var(--accent-h);
  }
  .status { font-size: 13px; color: var(--text-3); }
  .answer-body {
    font-size: 15.5px;
    line-height: 1.55;
    color: var(--text-1);
    user-select: text;
    -webkit-user-select: text;
  }
  .answer-body :global(p) { margin-bottom: 8px; }
  .answer-body :global(ul) { margin: 0 0 8px 18px; }
  .answer-body :global(li) { margin-bottom: 4px; }
  .answer-body :global(button.cite) {
    display: inline-block;
    min-width: 20px;
    margin: 0 1px;
    padding: 0 5px;
    font-size: 11.5px;
    font-weight: 700;
    line-height: 18px;
    text-align: center;
    vertical-align: 2px;
    color: var(--accent-h);
    background: var(--accent-dim);
    border-radius: 4px;
  }
  .disclaimer { font-size: 12px; color: var(--text-3); line-height: 1.45; margin-top: 4px; }
  .keywords { font-size: 12px; color: var(--text-3); margin-top: 8px; }

  .sources-title {
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: .06em;
    color: var(--text-3);
    margin-top: 6px;
  }
  .source { flex-shrink: 0; display: flex; flex-direction: column; gap: 6px; border-radius: var(--radius-lg); transition: box-shadow .3s; }
  .source:global(.flash) { box-shadow: 0 0 0 2px var(--accent); }
  .source-head { display: flex; align-items: center; gap: 8px; }
  .num {
    font-size: 11.5px;
    font-weight: 700;
    color: var(--accent-h);
    background: var(--accent-dim);
    border-radius: 4px;
    padding: 1px 7px;
  }
  .guideline { font-size: 12.5px; color: var(--text-2); }
  .extra { font-size: 11px; color: var(--text-3); margin-left: auto; }
  .qa { font-size: 13px; color: var(--text-3); line-height: 1.45; font-style: italic; }

  .empty { font-size: 14px; color: var(--text-3); text-align: center; padding: 30px 10px; }
  .err { font-size: 13.5px; color: #d6897b; }
  .err.small { font-size: 13px; }
</style>
