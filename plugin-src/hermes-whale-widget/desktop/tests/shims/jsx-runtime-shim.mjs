/** jsx-runtime shim: pass-through plain-object vnodes (test-only). */
export function jsx(type, props) {
  return { type, props }
}
export const jsxs = jsx
export const Fragment = 'Fragment'
