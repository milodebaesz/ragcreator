import { invoke } from '@tauri-apps/api/core'

import App from './App.svelte'

const target = document.getElementById('app')

async function boot() {
  try {
    // Resolves the data root (and moves it into iCloud on first run) before
    // any view reads from it.
    await invoke('init_storage')
  } catch (e) {
    // Every command falls back to resolving the data root itself.
    console.error('init_storage failed:', e)
  }
  return new App({ target })
}

export default boot()
