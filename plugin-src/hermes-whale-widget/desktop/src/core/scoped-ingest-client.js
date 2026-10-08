import { createIngestClient } from './ingest-client.js'

/** Keep queued turns and retries with their owning connection/profile. */
export function createScopedIngestClient({ getScope, rest, ...options }) {
  const clients = new Map()
  let active = null
  let disposed = false

  function selectScope() {
    const scope = getScope()
    if (active === scope) return clients.get(scope)
    if (active !== null) clients.get(active)?.pause()
    active = scope
    let client = clients.get(scope)
    if (!client) {
      const whenActive = callback => (...args) => {
        if (!disposed && scope === getScope()) callback?.(...args)
      }
      client = createIngestClient({
        ...options,
        rest: (path, body) => {
          if (disposed || scope !== getScope()) throw new Error('Accounting owner is not active')
          return rest(path, body)
        },
        onUnavailable: whenActive(options.onUnavailable),
        onRecovered: whenActive(options.onRecovered),
        onStats: whenActive(options.onStats),
        onSettled: whenActive(options.onSettled),
      })
      clients.set(scope, client)
    } else {
      client.resume()
    }
    return client
  }

  return {
    selectScope,
    submitTurn: payload => selectScope().submitTurn(payload),
    flushAndWait: () => selectScope().flushAndWait(),
    pause: () => selectScope().pause(),
    resume: () => selectScope().resume(),
    isPaused: () => selectScope().isPaused(),
    isUnavailable: () => selectScope().isUnavailable(),
    stats: () => selectScope().stats(),
    dispose() {
      disposed = true
      for (const client of clients.values()) client.pause()
    },
  }
}
