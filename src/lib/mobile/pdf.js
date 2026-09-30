// Loading guideline PDFs for the in-app viewer.
//
// The file comes from the backend as raw bytes (`read_project_pdf`) rather
// than a URL: it lives in the iCloud container, outside anything the webview
// may load directly.
import { writable } from 'svelte/store'
import { invoke } from '@tauri-apps/api/core'

// PDF.js is a large library only the phone's viewer uses; loading it on first
// use keeps it out of the desktop app's startup entirely.
let pdfjs = null
async function pdfLib() {
  if (!pdfjs) {
    pdfjs = Promise.all([
      import('pdfjs-dist'),
      import('pdfjs-dist/build/pdf.worker.min.mjs?url'),
    ]).then(([lib, worker]) => {
      lib.GlobalWorkerOptions.workerSrc = worker.default
      return lib
    })
  }
  return pdfjs
}

/**
 * The PDF opened over the whole app, e.g. from a recommendation card.
 * `{ project, page }` with a 1-based page, or null when closed.
 */
export const pdfView = writable(null)

export function openPdf(project, page) {
  pdfView.set({ project, page: page || 1 })
}

// One open document at a time: a parsed guideline holds tens of megabytes, and
// switching projects is rare enough that re-reading is cheaper than keeping
// several around on a phone.
let cached = null

/** The parsed PDF for a project, reusing the last one when it matches. */
export async function loadPdf(project) {
  if (cached?.project === project) return cached.promise

  if (cached) {
    const old = cached.promise
    old.then(doc => doc.destroy()).catch(() => {})
  }

  const promise = Promise.all([
    pdfLib(),
    invoke('read_project_pdf', { project }),
  ]).then(([{ getDocument }, buffer]) =>
    getDocument({
      data: new Uint8Array(buffer),
      // Nothing in a guideline needs script evaluation, and a WebView should
      // not run code that came out of a document.
      isEvalSupported: false,
    }).promise
  )
  cached = { project, promise }
  // A failed load must not stick: the next attempt should read the file again.
  promise.catch(() => {
    if (cached?.promise === promise) cached = null
  })
  return promise
}

/** Last page read per project, so the Richtlijn tab reopens where you were. */
export function rememberedPage(project) {
  try {
    return Number(localStorage.getItem(`pdf-page:${project}`)) || 1
  } catch {
    return 1
  }
}

export function rememberPage(project, page) {
  try {
    localStorage.setItem(`pdf-page:${project}`, String(page))
  } catch {
    // Storage can be unavailable; losing the position is harmless.
  }
}
