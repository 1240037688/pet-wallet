/**
 * Artifact + security-tooling smoke tests (M0):
 *   - the built artifact exists, parses as ESM, passes the import-whitelist
 *     scanner, and only imports the runtime-provided bare specifiers;
 *   - tools/check-security.mjs scanner flags known-bad patterns (smoke);
 *   - ingest-client payload builder shape (M1 contract precursor).
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { scanArtifact } from '../../../../tools/check-security.mjs'
import { buildTurnPayload } from '../src/core/ingest-client.js'

const HERE = path.dirname(fileURLToPath(import.meta.url))
const DESKTOP_DIR = path.resolve(HERE, '..')
const ARTIFACT = path.join(DESKTOP_DIR, 'plugin.js')

test('built artifact exists and is a single-file ESM', () => {
  assert.ok(fs.existsSync(ARTIFACT), 'run node tools/build-desktop.mjs first')
  const text = fs.readFileSync(ARTIFACT, 'utf8')
  assert.match(text, /^\/\*! whale-widget desktop half/) // generated banner
  const imports = [...text.matchAll(/^\s*import\s[^'"]*['"]([^'"]+)['"]/gm)].map((m) => m[1])
  for (const spec of imports) {
    assert.ok(
      spec === '@hermes/plugin-sdk' || spec === 'react' || spec === 'react/jsx-runtime' || spec === 'react/jsx-dev-runtime',
      `artifact imports non-whitelisted specifier: ${spec}`,
    )
  }
})

test('built artifact passes the security scanner (no findings)', () => {
  const findings = scanArtifact(fs.readFileSync(ARTIFACT, 'utf8'))
  assert.deepEqual(findings, [])
})

test('security scanner flags known-bad artifact shapes (smoke)', () => {
  const bad = [
    "import _x from 'lodash'",
    'const stealth = eval("1+1")',
    'Object.defineProperty(Array.prototype, "evil", {})',
    'const k = "sk-test-fake-artifact-vector"',
    'fetch("https://evil.example/x")',
  ].join('\n')
  const findings = scanArtifact(bad)
  const names = findings.map((f) => f.split(': ')[1])
  assert.ok(names.some((n) => n.startsWith('import outside whitelist')))
  assert.ok(names.includes('forbidden pattern "eval("'))
  assert.ok(names.includes('forbidden pattern "prototype patch"'))
  assert.ok(names.includes('forbidden pattern "API key shape (sk-)"'))
  assert.ok(names.includes('forbidden pattern "remote URL literal"'))
})

test('clean artifact shape produces no findings (scanner negative control)', () => {
  const good = [
    "import { host } from '@hermes/plugin-sdk'",
    "import { jsx } from 'react/jsx-runtime'",
    "import { useState } from 'react'",
    'export default { id: "whale-widget" }',
  ].join('\n')
  assert.deepEqual(scanArtifact(good), [])
})

test('buildTurnPayload produces the M1 ingest contract precursor shape', () => {
  const payload = buildTurnPayload(
    { session_id: 's1', profile: 'default', model: 'deepseek-chat', status: 'complete', usage: { input: 1, output: 2 } },
    { receivedAt: 12345 },
  )
  assert.deepEqual(payload, {
    session_id: 's1',
    profile: 'default',
    model: 'deepseek-chat',
    usage: { input: 1, output: 2 },
    received_at: 12345,
    status: 'complete',
    after_reconnect: false,
    replayed: false,
  })
  const aligned = buildTurnPayload({ session_id: 's1' }, { receivedAt: 1, afterReconnect: true, replayed: true })
  assert.equal(aligned.after_reconnect, true)
  assert.equal(aligned.replayed, true)
  assert.equal(buildTurnPayload({ session_id: 's1', status: 'interrupted' }, { receivedAt: 1 }).status, 'interrupted')
})
