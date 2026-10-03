/**
 * M6 whale mood state machine (node:test, injected clock):
 * press→release, click combo window, transient moods (happy/money) and their
 * 2.5s expiry, sticky waiting until cleared, STREAM_TICK mood-neutrality,
 * ERROR clearing waiting, press winning over a transient.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import { createWhaleState, CLICK_WINDOW_MS, TRANSIENT_MS } from '../src/core/whale-state.js'

function makeMachine() {
  let t = 0
  const machine = createWhaleState({ now: () => t })
  return { machine, advance: (ms) => { t += ms }, now: () => t }
}

test('press → physical press mood; release settles back to idle', () => {
  const { machine } = makeMachine()
  assert.equal(machine.snapshot().mood, 'idle')
  assert.equal(machine.press().mood, 'press')
  assert.equal(machine.release().mood, 'idle')
})

test('click combo accumulates inside the click window and resets outside it', () => {
  const { machine, advance } = makeMachine()
  assert.equal(machine.click().combo, 1)
  advance(600)
  assert.equal(machine.click().combo, 2)
  advance(600) // the window counts from the LAST click (600ms ago) → still a combo
  assert.equal(machine.click().combo, 3)
  assert.equal(CLICK_WINDOW_MS, 1_200)
  advance(1_201) // 1201ms since the last click → window missed
  assert.equal(machine.click().combo, 1)
})

test('TASK_COMPLETED → happy transient, expires back to idle after 2.5s', () => {
  const { machine, advance } = makeMachine()
  assert.equal(machine.event('TASK_COMPLETED').mood, 'happy')
  advance(TRANSIENT_MS - 1)
  assert.equal(machine.tick().mood, 'happy') // still inside the transient
  advance(1)
  assert.equal(machine.tick().mood, 'idle') // ts >= until → expired
  assert.equal(TRANSIENT_MS, 2_500)
})

test('USAGE_UPDATED → money transient; expiry returns to idle (or waiting)', () => {
  const { machine, advance } = makeMachine()
  assert.equal(machine.event('USAGE_UPDATED').mood, 'money')
  advance(TRANSIENT_MS)
  assert.equal(machine.tick().mood, 'idle')

  // waiting underneath → the transient expires INTO waiting
  assert.equal(machine.event('USAGE_UPDATED').mood, 'money')
  machine.event('USER_INPUT_REQUIRED')
  advance(TRANSIENT_MS)
  const s = machine.tick()
  assert.equal(s.mood, 'waiting')
  assert.equal(s.waiting, 'question')
})

test('waiting is sticky: survives ticks and transient expiry until cleared', () => {
  const { machine, advance } = makeMachine()
  machine.event('APPROVAL_REQUIRED')
  let s = machine.snapshot()
  assert.equal(s.mood, 'waiting')
  assert.equal(s.waiting, 'approval')

  advance(60_000) // far beyond any transient window
  s = machine.tick()
  assert.equal(s.mood, 'waiting')
  assert.equal(s.waiting, 'approval')

  machine.event('APPROVAL_CLEARED')
  s = machine.snapshot()
  assert.equal(s.mood, 'idle')
  assert.equal(s.waiting, null)
})

test('USER_INPUT_CLEARED also releases the question wait', () => {
  const { machine } = makeMachine()
  machine.event('USER_INPUT_REQUIRED')
  assert.equal(machine.snapshot().waiting, 'question')
  machine.event('USER_INPUT_CLEARED')
  assert.equal(machine.snapshot().waiting, null)
})

test('STREAM_TICK never touches the mood (and never extends a transient)', () => {
  const { machine, advance } = makeMachine()
  assert.equal(machine.event('STREAM_TICK').mood, 'idle')

  machine.event('TASK_COMPLETED') // happy until t=2500
  machine.event('STREAM_TICK') // must NOT re-arm the transient
  advance(TRANSIENT_MS + 1)
  assert.equal(machine.tick().mood, 'idle')
})

test('ERROR clears a pending wait but has no mood of its own', () => {
  const { machine } = makeMachine()
  machine.event('USER_INPUT_REQUIRED')
  assert.equal(machine.snapshot().mood, 'waiting')
  const s = machine.event('ERROR')
  assert.equal(s.mood, 'idle')
  assert.equal(s.waiting, null)
})

test('press wins over a transient but release hands control back honestly', () => {
  const { machine, advance } = makeMachine()
  machine.event('TASK_COMPLETED') // happy
  assert.equal(machine.press().mood, 'press')
  advance(100) // still inside the transient window
  assert.equal(machine.release().mood, 'happy') // transient resumes, not fabricated
})

test('press does not reset the click combo counter', () => {
  const { machine } = makeMachine()
  machine.click()
  machine.click()
  machine.press()
  const s = machine.click()
  assert.equal(s.combo, 3)
})

test('snapshots are plain data (mood/clickCount/waiting only)', () => {
  const { machine } = makeMachine()
  machine.click()
  machine.event('USER_INPUT_REQUIRED')
  assert.deepEqual(machine.snapshot(), { mood: 'waiting', clickCount: 1, waiting: 'question' })
})
