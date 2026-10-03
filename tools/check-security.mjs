#!/usr/bin/env node
/**
 * check-security.mjs — static self-check of the BUILT desktop artifact.
 *
 * Mirrors the spirit of the official desktop admission lint
 * (hermes_cli/plugin_validate_desktop.py) plus the project red lines:
 *   - single-file ESM import whitelist: only @hermes/plugin-sdk + react*
 *     bare specifiers (any other bare or URL import = runtime-loader reject);
 *   - no eval / new Function / dynamic import outside the whitelist;
 *   - no prototype pollution patterns;
 *   - no <script> injection / document.write / remote URL literals;
 *   - no credential shapes (sk-… / Bearer …).
 *
 * Project-wide SOURCE scanning (Python + JS, with a documented allowlist for
 * the redaction/filter code) lives in tools/check-security.py — run BOTH.
 *
 * Exit 0 = clean; exit 1 = findings (listed). `scanArtifact(text)` is exported
 * for node:test smoke coverage.
 */
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const ARTIFACT = path.join(ROOT, 'plugin-src/hermes-whale-widget/desktop/plugin.js')

const IMPORT_ALLOWED = ['@hermes/plugin-sdk', 'react', 'react/jsx-runtime', 'react/jsx-dev-runtime']

const FORBIDDEN_PATTERNS = [
  { name: 'eval(', re: /\beval\s*\(/ },
  { name: 'new Function', re: /\bnew\s+Function\b/ },
  { name: 'prototype patch', re: /(__proto__|Object\.defineProperty\s*\(\s*(Object|Array|String|Number|Promise)\.prototype|prototype\s*\[\s*['"])/ },
  { name: 'document.write', re: /document\.write\s*\(/ },
  { name: '<script> injection', re: /<script\b/i },
  { name: 'remote URL literal', re: /\bhttps?:\/\// },
  { name: 'data:/blob: URL', re: /\b(data|blob):(?!\s*)/ },
  { name: 'API key shape (sk-)', re: /\bsk-[A-Za-z0-9_\-]{8,}\b/ },
  { name: 'Authorization bearer shape', re: /\bBearer\s+[A-Za-z0-9._~+/=\-]{6,}/i },
]

/** Scan artifact text; returns a list of finding strings (empty = clean). */
export function scanArtifact(text) {
  const findings = []
  const lines = text.split('\n')

  lines.forEach((line, index) => {
    // import whitelist: static imports and dynamic import(...) specifiers
    const staticImport = line.match(/^\s*import\s[^'"]*['"]([^'"]+)['"]/)
    if (staticImport && !IMPORT_ALLOWED.includes(staticImport[1]) && !staticImport[1].startsWith('./')) {
      findings.push(`line ${index + 1}: import outside whitelist: "${staticImport[1]}"`)
    }
    for (const dyn of line.matchAll(/\bimport\s*\(\s*['"]([^'"]+)['"]\s*\)/g)) {
      if (!IMPORT_ALLOWED.includes(dyn[1]) && !dyn[1].startsWith('./')) {
        findings.push(`line ${index + 1}: dynamic import outside whitelist: "${dyn[1]}"`)
      }
    }
    for (const pattern of FORBIDDEN_PATTERNS) {
      if (pattern.re.test(line)) {
        findings.push(`line ${index + 1}: forbidden pattern "${pattern.name}"`)
      }
    }
  })

  return findings
}

function main() {
  if (!fs.existsSync(ARTIFACT)) {
    console.error(`artifact not found: ${ARTIFACT}`)
    console.error('run: node tools/build-desktop.mjs')
    process.exit(1)
  }
  const text = fs.readFileSync(ARTIFACT, 'utf8')
  const findings = scanArtifact(text)
  const rel = path.relative(ROOT, ARTIFACT)
  if (findings.length === 0) {
    console.log(`check-security: OK — ${rel} (import whitelist, no forbidden patterns, no credential shapes)`)
    return
  }
  console.error(`check-security: FAILED — ${rel}`)
  for (const finding of findings) console.error(`  - ${finding}`)
  process.exit(1)
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main()
}
