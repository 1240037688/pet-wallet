/**
 * Loader hook: map the runtime-loader's bare import whitelist onto local test
 * shims, so the BUILT artifact can be imported and register()d under node.
 */
const MAP = {
  '@hermes/plugin-sdk': new URL('./shims/sdk-shim.mjs', import.meta.url).href,
  react: 'data:text/javascript,export default {}', // unused by the artifact; kept for whitelist completeness
  'react/jsx-runtime': new URL('./shims/jsx-runtime-shim.mjs', import.meta.url).href,
}

export async function resolve(specifier, context, next) {
  if (MAP[specifier]) return { url: MAP[specifier], shortCircuit: true }
  return next(specifier, context)
}
