<script>
  import { invoke } from '@tauri-apps/api/core'
  import {
    activeProject, envConfig, projectStatus,
    stepStates, stepLogs,
    resetStepLogs, setStepState, appendStepLog,
  } from './stores.js'

  const STEPS = [
    {
      num: 1,
      name: 'PDF → Markdown',
      desc: 'Extraheert tekst uit de PDF via PyMuPDF en schrijft guideline.md.',
      input: 'PDF-bestand',
      output: 'guideline.md',
      needsPdf: true, needsOpenAI: false, needsMongo: false,
    },
    {
      num: 2,
      name: 'Structuur extractie',
      desc: 'Parseert Class/Level-aanbevelingen uit de markdown tabel.',
      input: 'guideline.md',
      output: 'rag_chunks.json',
      needsPdf: false, needsOpenAI: false, needsMongo: false,
    },
    {
      num: 3,
      name: 'QA-paren genereren',
      desc: 'Genereert klinische vraag/antwoord-paren via GPT-4.1-mini.',
      input: 'rag_chunks.json',
      output: 'qa_pairs.json',
      needsPdf: false, needsOpenAI: true, needsMongo: false,
    },
    {
      num: 4,
      name: 'Embeddings',
      desc: 'Maakt vectorembeddings (text-embedding-3-large, 3072 dim).',
      input: 'rag_chunks.json',
      output: 'embeddings.json',
      needsPdf: false, needsOpenAI: true, needsMongo: false,
    },
    {
      num: 5,
      name: 'Upload MongoDB',
      desc: 'Uploadt ingebedde documenten naar MongoDB Atlas via upsert.',
      input: 'embeddings.json',
      output: 'MongoDB collection',
      needsPdf: false, needsOpenAI: false, needsMongo: true,
    },
  ]

  let openLogStep = null
  let pickingPdf = false
  let refreshing = false

  $: status = $projectStatus
  $: states = $stepStates
  $: logs   = $stepLogs
  $: env    = $envConfig

  function isStepEnabled(step) {
    if (!status) return false
    switch (step.num) {
      case 1: return status.has_pdf
      case 2: return status.has_markdown
      case 3: return status.has_chunks
      case 4: return status.has_chunks
      case 5: return status.has_embeddings
      default: return false
    }
  }

  function stepIsDone(step) {
    switch (step.num) {
      case 1: return status?.has_markdown
      case 2: return status?.has_chunks
      case 3: return status?.has_qa
      case 4: return status?.has_embeddings
      case 5: return false // always re-runnable
      default: return false
    }
  }

  async function runStep(step) {
    if (states[step.num] === 'running') return
    resetStepLogs(step.num)
    setStepState(step.num, 'running')
    openLogStep = step.num

    try {
      await invoke('run_pipeline_step', {
        project:    $activeProject,
        step:       step.num,
        openaiKey:  env.openai_key  || null,
        mongodbUri: env.mongodb_uri || null,
        mongodbDb:  env.mongodb_db  || null,
        mongodbColl: env.mongodb_coll || null,
      })
      // done event handled in App.svelte → setStepState
    } catch (e) {
      setStepState(step.num, 'error')
      appendStepLog(step.num, `FOUT: ${e}`, true)
    }

    // Refresh status after step completes (small delay)
    setTimeout(refreshStatusStore, 1200)
  }

  async function refreshStatusStore() {
    if (!$activeProject) return
    refreshing = true
    try {
      const s = await invoke('get_project_status', { project: $activeProject })
      projectStatus.set(s)
    } finally {
      refreshing = false
    }
  }

  async function pickPdf() {
    pickingPdf = true
    try {
      const path = await invoke('pick_pdf')
      if (path) {
        await invoke('set_pdf_path', { project: $activeProject, pdfPath: path })
        await refreshStatusStore()
      }
    } catch (e) {
      console.error(e)
    } finally {
      pickingPdf = false
    }
  }

  function stateIcon(num) {
    const s = states[num]
    if (s === 'running') return '⟳'
    if (s === 'done')    return '✓'
    if (s === 'error')   return '✕'
    return stepIsDone({ num }) ? '✓' : '○'
  }

  function stateClass(num) {
    const s = states[num]
    if (s === 'running') return 'running'
    if (s === 'done')    return 'done'
    if (s === 'error')   return 'error'
    return stepIsDone({ num }) ? 'done' : 'idle'
  }

  function hasMissingKey(step) {
    if (step.needsOpenAI && !env.openai_key)  return 'OpenAI API-sleutel ontbreekt'
    if (step.needsMongo  && !env.mongodb_uri) return 'MongoDB URI ontbreekt'
    return null
  }
</script>

<div class="pipeline">
  <!-- Header row -->
  <div class="pipeline-header">
    <div class="header-left">
      <h2 class="pipeline-title">{$activeProject}</h2>
      {#if status}
        <span class="chunk-badge">
          {status.chunk_count} chunks
        </span>
      {/if}
    </div>
    <button class="refresh-btn" on:click={refreshStatusStore} disabled={refreshing}>
      {refreshing ? '⟳' : '↺'} Vernieuwen
    </button>
  </div>

  <!-- PDF row -->
  <div class="pdf-row">
    <div class="pdf-info">
      {#if status?.has_pdf}
        <span class="pdf-dot ok"></span>
        <span class="pdf-label">PDF gekoppeld</span>
      {:else}
        <span class="pdf-dot missing"></span>
        <span class="pdf-label missing-text">Geen PDF — selecteer hieronder</span>
      {/if}
    </div>
    <button class="btn-secondary" on:click={pickPdf} disabled={pickingPdf}>
      {pickingPdf ? 'Kiezen…' : '📂 PDF kiezen'}
    </button>
  </div>

  <!-- Steps -->
  <div class="steps">
    {#each STEPS as step}
      {@const sc    = stateClass(step.num)}
      {@const warn  = hasMissingKey(step)}
      {@const enabled = isStepEnabled(step)}
      {@const isOpen  = openLogStep === step.num}

      <div class="step-card" class:active={sc === 'running' || sc === 'done'}>
        <!-- Step header -->
        <div class="step-header">
          <div class="step-num-col">
            <div class="step-bubble {sc}">{stateIcon(step.num)}</div>
          </div>

          <div class="step-meta">
            <div class="step-top">
              <span class="step-name">{step.name}</span>
              <div class="step-io">
                <span class="io-tag in">{step.input}</span>
                <span class="io-arrow">→</span>
                <span class="io-tag out">{step.output}</span>
              </div>
            </div>
            <p class="step-desc">{step.desc}</p>
            {#if warn}
              <p class="step-warn">⚠ {warn} — stel in via Instellingen</p>
            {/if}
          </div>

          <div class="step-actions">
            {#if sc === 'running'}
              <button class="btn-run running" disabled>
                <span class="spinner">⟳</span> Bezig…
              </button>
            {:else}
              <button
                class="btn-run"
                class:secondary={stepIsDone(step)}
                on:click={() => runStep(step)}
                disabled={!enabled || !!warn}
                title={!enabled ? 'Vorige stap eerst uitvoeren' : warn ?? ''}
              >
                {stepIsDone(step) ? '↺ Opnieuw' : '▶ Starten'}
              </button>
            {/if}

            {#if logs[step.num]?.length > 0}
              <button
                class="btn-log-toggle"
                on:click={() => openLogStep = isOpen ? null : step.num}
              >
                {isOpen ? '↑ Log' : '↓ Log'}
                <span class="log-count">{logs[step.num].length}</span>
              </button>
            {/if}
          </div>
        </div>

        <!-- Log output -->
        {#if isOpen && logs[step.num]?.length > 0}
          <div class="log-panel">
            {#each logs[step.num] as entry}
              <div class="log-line" class:stderr={entry.isStderr}>{entry.line}</div>
            {/each}
          </div>
        {/if}
      </div>
    {/each}
  </div>
</div>

<style>
  .pipeline {
    padding: 24px 28px;
    overflow-y: auto;
    height: 100%;
    display: flex;
    flex-direction: column;
    gap: 20px;
  }

  /* Header */
  .pipeline-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .header-left { display: flex; align-items: center; gap: 12px; }
  .pipeline-title { font-size: 20px; font-weight: 600; }
  .chunk-badge {
    padding: 2px 10px;
    background: var(--accent-dim);
    color: var(--accent-h);
    border-radius: 20px;
    font-size: 12px;
    font-weight: 600;
  }
  .refresh-btn {
    padding: 6px 14px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    color: var(--text-2);
    font-size: 12px;
    transition: background .12s, color .12s;
  }
  .refresh-btn:hover { background: var(--bg-hover); color: var(--text-1); }

  /* PDF row */
  .pdf-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 12px 16px;
  }
  .pdf-info { display: flex; align-items: center; gap: 8px; }
  .pdf-dot  {
    width: 8px; height: 8px; border-radius: 50%;
    flex-shrink: 0;
  }
  .pdf-dot.ok      { background: var(--success); box-shadow: 0 0 6px var(--success); }
  .pdf-dot.missing { background: var(--text-3); }
  .pdf-label       { font-size: 13px; color: var(--text-2); }
  .missing-text    { color: var(--text-3); }

  .btn-secondary {
    padding: 7px 14px;
    border-radius: var(--radius);
    border: 1px solid var(--border);
    font-size: 13px;
    color: var(--text-1);
    transition: background .12s;
  }
  .btn-secondary:hover    { background: var(--bg-hover); }
  .btn-secondary:disabled { opacity: .5; cursor: not-allowed; }

  /* Steps */
  .steps { display: flex; flex-direction: column; gap: 10px; }

  .step-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    transition: border-color .2s;
  }
  .step-card.active { border-color: var(--accent); }

  .step-header {
    display: flex;
    align-items: flex-start;
    gap: 16px;
    padding: 16px 18px;
  }

  /* Step bubble */
  .step-num-col { padding-top: 2px; }
  .step-bubble {
    width: 32px; height: 32px;
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700;
    border: 2px solid var(--border);
    color: var(--text-3);
    flex-shrink: 0;
  }
  .step-bubble.idle    { }
  .step-bubble.running {
    border-color: var(--accent);
    color: var(--accent-h);
    animation: spin 1s linear infinite;
  }
  .step-bubble.done  {
    border-color: var(--success);
    background: var(--success-dim);
    color: var(--success);
  }
  .step-bubble.error {
    border-color: var(--error);
    background: var(--error-dim);
    color: var(--error);
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* Step meta */
  .step-meta { flex: 1; min-width: 0; }
  .step-top {
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
    margin-bottom: 4px;
  }
  .step-name { font-size: 14px; font-weight: 600; }
  .step-io   { display: flex; align-items: center; gap: 6px; }
  .io-tag {
    font-size: 11px;
    padding: 2px 8px;
    border-radius: 4px;
    font-family: var(--mono);
  }
  .io-tag.in  { background: var(--bg-hover); color: var(--text-2); }
  .io-tag.out { background: var(--accent-dim); color: var(--accent-h); }
  .io-arrow   { font-size: 12px; color: var(--text-3); }
  .step-desc  { font-size: 12px; color: var(--text-2); }
  .step-warn  {
    margin-top: 4px;
    font-size: 12px;
    color: var(--warn);
  }

  /* Action buttons */
  .step-actions {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 6px;
    flex-shrink: 0;
  }
  .btn-run {
    padding: 7px 16px;
    border-radius: var(--radius);
    background: var(--accent);
    color: #fff;
    font-size: 13px;
    font-weight: 600;
    transition: background .12s, opacity .12s;
    min-width: 100px;
    text-align: center;
  }
  .btn-run:hover    { background: var(--accent-h); }
  .btn-run:disabled { opacity: .4; cursor: not-allowed; }
  .btn-run.secondary {
    background: transparent;
    border: 1px solid var(--border);
    color: var(--text-2);
  }
  .btn-run.secondary:hover { background: var(--bg-hover); color: var(--text-1); }
  .btn-run.running  { background: var(--accent-dim); color: var(--accent-h); cursor: default; }
  .spinner          { display: inline-block; animation: spin 1s linear infinite; }

  .btn-log-toggle {
    display: flex; align-items: center; gap: 6px;
    font-size: 11px;
    color: var(--text-3);
    padding: 3px 8px;
    border-radius: 4px;
    border: 1px solid var(--border);
    transition: background .12s;
  }
  .btn-log-toggle:hover { background: var(--bg-hover); color: var(--text-2); }
  .log-count {
    background: var(--bg-hover);
    padding: 1px 5px;
    border-radius: 3px;
    font-size: 10px;
  }

  /* Log panel */
  .log-panel {
    background: #0a0b14;
    border-top: 1px solid var(--border);
    padding: 12px 16px;
    max-height: 220px;
    overflow-y: auto;
    font-family: var(--mono);
    font-size: 12px;
    line-height: 1.6;
  }
  .log-line        { color: #94a3b8; white-space: pre-wrap; word-break: break-all; }
  .log-line.stderr { color: #fca5a5; }
</style>
