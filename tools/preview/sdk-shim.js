/**
 * SDK shim for the dev preview page (tools/dev-preview.mjs).
 *
 * Stubs the minimal @hermes/plugin-sdk surface the M0 artifact uses:
 *   STATUSBAR_AREAS, atom, useValue, host.notify — plus no-op onEvent/
 *   onDispose doors via the preview ctx (see preview-host.js).
 *
 * DEV TOOL ONLY — never ships in the release artifact. Bundled with real
 * react (devDependency) by dev-preview.mjs so useValue is a genuine hook.
 */
import { useSyncExternalStore } from 'react'

export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' }
export const PANES_AREA = 'panes'

/** Minimal nanostores-compatible atom: get/set/subscribe. */
export function atom(initial) {
  let value = initial
  const listeners = new Set()
  return {
    get: () => value,
    set(next) {
      value = typeof next === 'function' ? next(value) : next
      for (const listener of listeners) listener()
    },
    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
  }
}

/** React hook over the atom (real React via useSyncExternalStore). */
export function useValue(store) {
  return useSyncExternalStore(store.subscribe, store.get, store.get)
}

function toast(message, isError) {
  const host_ = document.getElementById('whale-toasts')
  if (!host_) return
  const el = document.createElement('div')
  el.className = 'whale-toast' + (isError ? ' whale-toast-error' : '')
  el.textContent = `host.notify: ${message}`
  host_.appendChild(el)
  setTimeout(() => el.remove(), 5000)
}

export const host = {
  notify: ({ message } = {}) => toast(String(message ?? ''), false),
  notifyError: ({ message } = {}) => toast(String(message ?? 'error'), true),
}

export default { STATUSBAR_AREAS, PANES_AREA, atom, useValue, host }
