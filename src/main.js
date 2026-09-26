import { invoke } from '@tauri-apps/api/core'

import App from './App.svelte'
import MobileApp from './MobileApp.svelte'

const target = document.getElementById('app')

// Which app to mount is a backend fact, not a screen-size guess: the iOS build
// registers a different, read-only set of commands, and a user-agent sniff
// would mount the wrong one on an iPad reporting itself as a Mac.
async function boot() {
  let storage = null
  try {
    storage = await invoke('init_storage')
  } catch (e) {
    // Desktop can run without it — every command falls back to resolving the
    // data root itself. Mobile cannot get here: init_storage never fails there,
    // it falls back to local storage instead.
    console.error('init_storage failed:', e)
  }

  if (storage?.read_only) {
    return new MobileApp({ target, props: { storage } })
  }
  return new App({ target })
}

export default boot()
