import { writable, derived } from 'svelte/store'

// ── Global app state ──────────────────────────────────────────────────────────
export const config        = writable(null)   // raw Config from Rust
export const activeProject = writable(null)   // string | null
export const activeTab     = writable('pipeline') // 'pipeline'|'info'|'results'|'qa'|'search'|'settings'

// ── API / connection settings ─────────────────────────────────────────────────
export const envConfig = writable({
  openai_key:   '',
  mongodb_uri:  '',
  mongodb_db:   'rag_db',
  mongodb_coll: 'rag_chunks',
})

// ── Project status (refreshed after each step) ────────────────────────────────
export const projectStatus = writable(null)

// ── Pipeline state per project, per step (1–5) ────────────────────────────────
//
// Every project (guideline) has its own pipeline: running a step in one
// guideline must never show up as running/done in another. Both stores are
// therefore keyed by project name first, step number second. Steps keep
// running in the background when you switch projects, and their logs are
// still there when you switch back.
//
// state: 'idle' | 'running' | 'done' | 'error'
export const stepStates = writable({}) // { [project]: { 1:'idle', … } }
export const stepLogs   = writable({}) // { [project]: { 1:[], … } }

const emptyStates = () => ({ 1:'idle', 2:'idle', 3:'idle', 4:'idle', 5:'idle' })
const emptyLogs   = () => ({ 1:[],     2:[],     3:[],     4:[],     5:[]     })

export function resetStepLogs(project, stepNum) {
  if (!project) return
  stepLogs.update(all => {
    const forProject = all[project] ?? emptyLogs()
    return { ...all, [project]: { ...forProject, [stepNum]: [] } }
  })
}

export function appendStepLog(project, stepNum, line, isStderr) {
  if (!project) return
  stepLogs.update(all => {
    const forProject = all[project] ?? emptyLogs()
    return {
      ...all,
      [project]: {
        ...forProject,
        [stepNum]: [...(forProject[stepNum] ?? []), { line, isStderr }],
      },
    }
  })
}

export function setStepState(project, stepNum, state) {
  if (!project) return
  stepStates.update(all => {
    const forProject = all[project] ?? emptyStates()
    return { ...all, [project]: { ...forProject, [stepNum]: state } }
  })
}

/** Drop all pipeline state for a project (e.g. when it is deleted). */
export function clearProjectPipeline(project) {
  if (!project) return
  stepStates.update(all => { const { [project]: _, ...rest } = all; return rest })
  stepLogs.update(all   => { const { [project]: _, ...rest } = all; return rest })
}

// ── Derived: pipeline state of the currently active project ──────────────────
export const activeStepStates = derived(
  [stepStates, activeProject],
  ([$s, $p]) => ($p && $s[$p]) || emptyStates(),
)

export const activeStepLogs = derived(
  [stepLogs, activeProject],
  ([$l, $p]) => ($p && $l[$p]) || emptyLogs(),
)

// ── Derived: list of project names ───────────────────────────────────────────
export const projectNames = derived(config, $c => $c?.projects ?? [])
