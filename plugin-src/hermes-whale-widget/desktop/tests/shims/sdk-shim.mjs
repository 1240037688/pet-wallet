/**
 * Minimal @hermes/plugin-sdk shim for loading the BUILT ARTIFACT under node
 * (module.register loader hook, tests/loader.mjs). Test-only.
 */

export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' }
export const PANES_AREA = 'panes'

export const notifications = []

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

export function useValue(store) {
  return store.get()
}

export const host = {
  notify: (input = {}) => notifications.push(input),
  notifyError: (input = {}) => notifications.push({ error: true, ...input }),
}
