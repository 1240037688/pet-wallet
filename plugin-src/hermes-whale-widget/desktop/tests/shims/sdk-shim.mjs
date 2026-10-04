/**
 * Minimal @hermes/plugin-sdk shim for loading the BUILT ARTIFACT under node
 * (module.register loader hook, tests/loader.mjs). Test-only.
 *
 * WP-dashboard additions (additive, keep existing exports stable):
 *   - ROUTES_AREA / SIDEBAR_NAV_AREA constants;
 *   - host.navigate (records into `navigations` for wiring assertions);
 *   - inert component stubs + query stubs — the dashboard page is only
 *     INVOKED by the real SDK React runtime, never in these tests.
 */

export const STATUSBAR_AREAS = { left: 'statusBar.left', right: 'statusBar.right' }
export const PANES_AREA = 'panes'
export const ROUTES_AREA = 'routes'
export const SIDEBAR_NAV_AREA = 'sidebar.nav'

export const notifications = []
export const navigations = []

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

export function useQuery() {
  return { data: undefined, error: null, isLoading: true, isFetching: false, refetch: async () => {} }
}

export function useQueryClient() {
  return { invalidateQueries: () => {} }
}

export const host = {
  notify: (input = {}) => notifications.push(input),
  notifyError: (input = {}) => notifications.push({ error: true, ...input }),
  navigate: (path) => navigations.push(path),
}

// Inert component stubs (the page render path is not exercised under node).
export const Button = () => null
export const EmptyState = () => null
export const ErrorState = () => null
export const Select = () => null
export const SelectContent = () => null
export const SelectItem = () => null
export const SelectTrigger = () => null
export const SelectValue = () => null
export const ToggleRow = () => null
