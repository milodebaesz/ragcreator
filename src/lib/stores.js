import { writable, derived } from 'svelte/store'

// ── Global app state ──────────────────────────────────────────────────────────
export const config        = writable(null)   // raw Config from Rust
export const activeProject = writable(null)   // string | null
export const activeTab     = writable('pipeline') // 'pipeline'|'results'|'search'|'settings'

// ── API / connection settings ─────────────────────────────────────────────────
export const envConfig = writable({
  openai_key:   '',
  mongodb_uri:  '',
  mongodb_db:   'rag_db',
  mongodb_coll: 'rag_chunks',
})

// ── Project status (refreshed after each step) ────────────────────────────────
export const projectStatus = writable(null)

// ── Pipeline state per step (1–5) ─────────────────────────────────────────────
// state: 'idle' | 'running' | 'done' | 'error'
export const stepStates = writable({ 1:'idle',2:'idle',3:'idle',4:'idle',5:'idle' })
export const stepLogs   = writable({ 1:[],    2:[],    3:[],    4:[],    5:[]    })

export function resetStepLogs(stepNum) {
  stepLogs.update(l => ({ ...l, [stepNum]: [] }))
}

export function appendStepLog(stepNum, line, isStderr) {
  stepLogs.update(l => ({
    ...l,
    [stepNum]: [...l[stepNum], { line, isStderr }],
  }))
}

export function setStepState(stepNum, state) {
  stepStates.update(s => ({ ...s, [stepNum]: state }))
}

// ── Derived: list of project names ───────────────────────────────────────────
export const projectNames = derived(config, $c => $c?.projects ?? [])
