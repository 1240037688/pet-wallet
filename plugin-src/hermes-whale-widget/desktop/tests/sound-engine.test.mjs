/**
 * L1 tests for the M9 sound engine (node:test). All Web Audio goes through
 * the injected contextFactory — a fake context records start/stop/suspend/
 * resume/decode call sequences; no real audio device is touched.
 *
 * Covers: lazy context + factory args, synchronous start path (undecoded clip
 * skips that play while the background decode continues), release scheduling
 * (short-press splice at pressStart + duration − 40ms, long-press immediate),
 * tri-state volume (unset follows global / explicit own value / clamp), mute
 * priority (no context while muted, kills playing nodes), event→clip mapping
 * defaults + explicit silence, sound group override, URL-level cache dedup +
 * terminal failure states, idle suspend/resume (injected clock + opt-in
 * timer), dispose, preview bypassing mute, pure helpers.
 */
import test from 'node:test'
import assert from 'node:assert/strict'

import {
  DEFAULT_CLIPS,
  IDLE_SUSPEND_MS,
  RELEASE_LEAD_SEC,
  SOUND_EVENTS,
  clampVolume,
  computeReleaseStart,
  createSoundEngine,
  resolveVolume,
} from '../src/sound/engine.js'

// ---------- fake Web Audio ----------

function createFakeContext(log, { decodeError = null } = {}) {
  const context = {
    state: 'running',
    currentTime: 0,
    destination: { name: 'destination' },
    decodeCalls: 0,
    resumeCalls: 0,
    suspendCalls: 0,
    sources: [],
    gains: [],
    decodeAudioData(data) {
      context.decodeCalls += 1
      log.push(['decode'])
      if (decodeError) return Promise.reject(decodeError)
      return Promise.resolve({ duration: Number(data && data.duration) || 0, sampleRate: 48000 })
    },
    resume() {
      context.resumeCalls += 1
      log.push(['resume'])
      return Promise.resolve()
    },
    suspend() {
      context.suspendCalls += 1
      log.push(['suspend'])
      return Promise.resolve()
    },
    createBufferSource() {
      const source = {
        buffer: null,
        onended: null,
        connectedTo: null,
        starts: [],
        stops: 0,
        connect(dest) {
          source.connectedTo = dest
          return dest
        },
        start(when) {
          source.starts.push(when)
          log.push(['start', when])
        },
        stop() {
          source.stops += 1
          log.push(['stop'])
        },
      }
      context.sources.push(source)
      return source
    },
    createGain() {
      const gain = {
        gain: { value: 1 },
        connectedTo: null,
        connect(dest) {
          gain.connectedTo = dest
          return dest
        },
        disconnect() {},
      }
      context.gains.push(gain)
      return gain
    },
  }
  return context
}

/**
 * Test environment: fake context factory + recorded fetches + injected clock.
 * clipData maps url → "encoded payload" (the fake decoder echoes its .duration
 * back as the decoded AudioBuffer duration; default duration is 1s).
 */
function makeEnv({ clips = {}, clipData = {}, decodeError = null, captureTimer = false } = {}) {
  const log = []
  const contexts = []
  const fetched = []
  const debugEvents = []
  const factoryArgs = []
  let factoryCalls = 0
  let timer = { fn: null, ms: null, count: 0 }
  let nowMs = 0

  const contextFactory = (options) => {
    factoryCalls += 1
    factoryArgs.push(options)
    const context = createFakeContext(log, { decodeError })
    contexts.push(context)
    return context
  }

  const fetchClip = (url) => {
    fetched.push(url)
    return Promise.resolve(clipData[url] === undefined ? { duration: 1 } : clipData[url])
  }

  const engine = createSoundEngine({
    contextFactory,
    now: () => nowMs,
    fetchClip,
    onDebug: (kind, info) => debugEvents.push({ kind, info }),
    setTimer: captureTimer
      ? (fn, ms) => {
          timer.fn = fn
          timer.ms = ms
          timer.count += 1
          return timer.count
        }
      : null,
  })

  for (const [event, url] of Object.entries(clips)) engine.setClip(event, url)

  // drain microtasks (+ one macrotask) so background fetch/decode settles
  const flush = () => new Promise((resolve) => setTimeout(resolve, 0))

  return {
    engine,
    log,
    contexts,
    fetched,
    debugEvents,
    flush,
    ctx: () => contexts[0],
    factoryCalls: () => factoryCalls,
    factoryArgs,
    timer,
    setNow: (value) => {
      nowMs = value
    },
  }
}

async function readyEnv(options) {
  const env = makeEnv(options)
  env.engine.warm()
  await env.flush()
  return env
}

// ---------- 1. lazy context creation + factory contract ----------

test('lazy context: no clips mapped → no context built; first play builds exactly one, with latencyHint', async () => {
  const env = makeEnv()
  assert.equal(env.engine.press(), null)
  assert.equal(env.factoryCalls(), 0) // 默认全 null 映射：连 context 都不建
  assert.equal(env.fetched.length, 0)

  env.engine.setClip('press', 'u:press')
  const first = env.engine.press() // clip 起码开始解码；context 此时才创建
  assert.equal(first, null)
  assert.equal(env.factoryCalls(), 1)
  assert.deepEqual(env.factoryArgs[0], { latencyHint: 'interactive' })

  await env.flush()
  const second = env.engine.press()
  assert.equal(second.url, 'u:press')
  assert.equal(env.factoryCalls(), 1) // 复用同一个 context
})

// ---------- 2. synchronous start path ----------

test('sync start: ready clip starts immediately on press, correct node chain and default volume', async () => {
  const env = await readyEnv({ clips: { press: 'u:press' } })
  env.ctx().currentTime = 10

  const result = env.engine.press()
  assert.deepEqual(
    { url: result.url, when: result.when, volume: result.volume, duration: result.duration },
    { url: 'u:press', when: 10, volume: 1, duration: 1 },
  )

  const source = env.ctx().sources[0]
  const gain = env.ctx().gains[0]
  assert.deepEqual(source.starts, [10]) // 音频线程时刻排期
  assert.equal(source.buffer.duration, 1)
  assert.equal(source.connectedTo, gain)
  assert.equal(gain.connectedTo, env.ctx().destination)
  assert.equal(gain.gain.value, 1)
})

test('undecoded clip: press skips (no await), background decode continues, next press plays; one fetch only', async () => {
  const env = makeEnv({ clips: { press: 'u:press' } })

  assert.equal(env.engine.press(), null) // 未就绪 → 跳过本次（同步路径不 await）
  assert.equal(env.engine.press(), null) // 仍在解码 → 再次跳过
  assert.equal(env.ctx().sources.length, 0)
  assert.equal(env.fetched.length, 0) // fetch 在微任务中启动

  await env.flush()
  assert.deepEqual(env.fetched, ['u:press']) // 只取流一次
  assert.equal(env.ctx().decodeCalls, 1)

  const result = env.engine.press()
  assert.equal(result.url, 'u:press')
  assert.deepEqual(env.fetched, ['u:press']) // 后续播放不再取流
})

// ---------- 3. release scheduling (playAt on the audio clock) ----------

test('short press: release sound scheduled at pressStart + pressDuration − 40ms', async () => {
  const env = await readyEnv({
    clips: { press: 'u:press', release: 'u:release' },
    clipData: { 'u:press': { duration: 1.0 }, 'u:release': { duration: 0.5 } },
  })
  env.ctx().currentTime = 10
  env.engine.press()
  env.ctx().currentTime = 10.2 // 100ms 后松手（剩余 0.8s）

  const result = env.engine.release()
  assert.equal(result.url, 'u:release')
  assert.equal(result.when, 10.96) // 10 + 1.0 − 0.04
  assert.deepEqual(env.ctx().sources[1].starts, [10.96])

  // 锚点已被消费：再次 release 无锚点 → 立即播
  const again = env.engine.release()
  assert.equal(again.when, 10.2)
})

test('long press (splice point already passed): release plays immediately at max(now, splice)', async () => {
  const env = await readyEnv({ clips: { press: 'u:press', release: 'u:release' } })
  env.ctx().currentTime = 10
  env.engine.press() // press duration 1.0 → splice point 10.96
  env.ctx().currentTime = 11.5

  const result = env.engine.release()
  assert.equal(result.when, 11.5) // 取 max(now, 排期点)
  assert.deepEqual(env.ctx().sources[1].starts, [11.5])
})

test('release without a press anchor plays immediately at the audio clock now', async () => {
  const env = await readyEnv({ clips: { release: 'u:release' } })
  env.ctx().currentTime = 7.25

  const result = env.engine.release()
  assert.equal(result.when, 7.25)
  assert.deepEqual(env.ctx().sources[0].starts, [7.25])
})

test('press clip without duration info degrades to immediate release', async () => {
  const env = makeEnv({ clips: { press: 'u:press', release: 'u:release' }, clipData: { 'u:press': {} } })
  env.engine.warm()
  await env.flush()
  env.ctx().currentTime = 3
  env.engine.press() // duration 0 → 无剩余时长概念
  env.ctx().currentTime = 3.5

  const result = env.engine.release()
  assert.equal(result.when, 3.5)
})

// ---------- 4. tri-state volume ----------

test('unset event volume follows the global press volume (live)', async () => {
  const env = await readyEnv({ clips: { task_finished: 'u:t' } })

  assert.equal(env.engine.play('task_finished').volume, 1) // 默认 100%
  env.engine.setVolume('global', 0.4)
  assert.equal(env.engine.play('task_finished').volume, 0.4)
  assert.equal(env.ctx().gains[1].gain.value, 0.4)
})

test('volSet tri-state: default 100% still follows global; explicit 100% uses its own value', async () => {
  const env = await readyEnv({ clips: { question: 'u:q' } })

  env.engine.setVolume('question', 1) // 未显式拖过滑块（explicit 缺省 false）
  env.engine.setVolume('global', 0.3)
  assert.equal(env.engine.play('question').volume, 0.3) // 跟随全局

  env.engine.setVolume('question', 1, { explicit: true }) // 用户显式设了 100%
  assert.equal(env.engine.play('question').volume, 1) // 用自身值
  env.engine.setVolume('global', 0.9)
  assert.equal(env.engine.play('question').volume, 1) // 全局变化不再影响
})

test('per-kind volumes are independent (press vs release vs events)', async () => {
  const env = await readyEnv({ clips: { press: 'u:p', release: 'u:r' } })
  env.engine.setVolume('press', 0.2, { explicit: true })
  env.engine.setVolume('release', 0.5, { explicit: true })

  env.ctx().currentTime = 20
  env.engine.press()
  env.engine.release() // 短按衔接：排期到 20 + 1.0 − 0.04
  assert.deepEqual(env.ctx().sources[0].starts, [20])
  assert.deepEqual(env.ctx().sources[1].starts, [20.96])
  assert.equal(env.ctx().gains[0].gain.value, 0.2)
  assert.equal(env.ctx().gains[1].gain.value, 0.5)
})

test('setVolume clamps to [0,1] and ignores non-numeric values', async () => {
  const env = await readyEnv({ clips: { task_finished: 'u:t' } })

  env.engine.setVolume('global', 2)
  assert.equal(env.engine.play('task_finished').volume, 1)
  env.engine.setVolume('global', -1)
  assert.equal(env.engine.play('task_finished').volume, 0)
  env.engine.setVolume('global', Number.NaN)
  assert.equal(env.engine.play('task_finished').volume, 0) // 保持原值
  assert.equal(clampVolume(0.7), 0.7)
  assert.equal(clampVolume('x'), null)
})

// ---------- 5. mute priority ----------

test('muted engine: no context, no fetch, no sound; unmute resumes normal playback', async () => {
  const env = makeEnv({ clips: { press: 'u:press' } })
  env.engine.setMuted(true)

  assert.equal(env.engine.press(), null)
  assert.equal(env.factoryCalls(), 0) // 总开关关闭：不建 context
  assert.equal(env.fetched.length, 0) // 不预热不取流

  env.engine.setMuted(false)
  assert.equal(env.engine.press(), null) // 冷缓存：跳过本次
  await env.flush()
  assert.equal(env.engine.press().url, 'u:press') // 解码完成后恢复
})

test('mute kills currently playing / already scheduled nodes; release after mute is silent', async () => {
  const env = await readyEnv({ clips: { press: 'u:press', release: 'u:release' } })
  env.ctx().currentTime = 10
  env.engine.press() // 播放中
  env.engine.release() // 已排期到 10.96 的节点
  assert.equal(env.ctx().sources.length, 2)

  env.engine.setMuted(true)
  assert.equal(env.ctx().sources[0].stops, 1)
  assert.equal(env.ctx().sources[1].stops, 1)
  assert.equal(env.engine.release(), null)
})

// ---------- 6. event→clip mapping table ----------

test('default mapping: every known event silent, unknown events silent, structure intact', () => {
  const env = makeEnv()
  for (const event of SOUND_EVENTS) {
    assert.equal(env.engine.play(event), null, `${event} should be silent by default`)
  }
  assert.equal(env.engine.play('nonexistent_kind'), null) // 未知事件不 throw、无声
  assert.equal(env.factoryCalls(), 0)
  assert.deepEqual(DEFAULT_CLIPS, {
    press: null,
    release: null,
    task_finished: null,
    question: null,
    approval: null,
  })
})

test('setClip: mapping set / explicit silence (empty string) / cleared back to null', async () => {
  const env = makeEnv()
  env.engine.setClip('task_finished', 'u:t')
  env.engine.warm()
  await env.flush()
  assert.equal(env.engine.play('task_finished').url, 'u:t')

  env.engine.setClip('task_finished', '') // 空串 = 显式静音
  assert.equal(env.engine.play('task_finished'), null)
  env.engine.setClip('task_finished', null)
  assert.equal(env.engine.play('task_finished'), null)
  env.engine.setClip('task_finished', 42) // 非字符串按静音处理
  assert.equal(env.engine.play('task_finished'), null)
})

// ---------- 7. sound group (minimal) ----------

test('sound group: empty slot = silent (no fallback), absent slot falls through, null group restores base', async () => {
  const env = await readyEnv({ clips: { press: 'u:press', question: 'u:q' } })

  env.engine.setSoundGroup({ id: 'g1', clips: { press: '', release: 'u:group-release' } })
  assert.equal(env.engine.press(), null) // 组槽位留空 = 该事件静音，不回退 'u:press'
  assert.equal(env.engine.play('question').url, 'u:q') // 组未涉及的槽位回退基础映射

  const release = env.engine.release() // 组内 release 指向未解码片段 → 跳过并后台解码
  assert.equal(release, null)
  await env.flush()
  assert.deepEqual(env.fetched, ['u:press', 'u:q', 'u:group-release'])
  assert.equal(env.engine.release().url, 'u:group-release')

  env.engine.setSoundGroup(null)
  assert.equal(env.engine.press().url, 'u:press') // 回到基础映射
})

// ---------- 8. URL-level cache ----------

test('same URL across events: one fetch, one decode, shared buffer', async () => {
  const env = makeEnv({ clips: { task_finished: 'u:shared', approval: 'u:shared' } })
  env.engine.warm()
  await env.flush()

  assert.deepEqual(env.fetched, ['u:shared'])
  assert.equal(env.ctx().decodeCalls, 1)

  assert.equal(env.engine.play('task_finished').url, 'u:shared')
  assert.equal(env.engine.play('approval').url, 'u:shared')
  assert.deepEqual(env.fetched, ['u:shared'])
  assert.equal(env.ctx().decodeCalls, 1)
})

// ---------- 9. terminal cache states ----------

test('decode failure cached: no retry, debug callback, never throws', async () => {
  const env = makeEnv({
    clips: { press: 'u:bad' },
    decodeError: new Error('mock EncodingError'),
  })
  env.engine.warm()
  await env.flush()

  assert.equal(env.engine.press(), null)
  assert.equal(env.engine.press(), null)
  assert.deepEqual(env.fetched, ['u:bad']) // 只取流一次
  assert.equal(env.ctx().decodeCalls, 1) // 失败态缓存：不再重试
  assert.ok(
    env.debugEvents.some((entry) => entry.kind === 'clip.decode.failed' && entry.info.url === 'u:bad'),
  )
})

test('empty response (204-style) intercepted before decode and cached as silence', async () => {
  const env = makeEnv({ clips: { release: 'u:empty' }, clipData: { 'u:empty': null } })
  env.engine.warm()
  await env.flush()

  assert.equal(env.engine.release(), null)
  assert.equal(env.ctx().decodeCalls, 0) // 0 字节绝不进 decodeAudioData
  assert.deepEqual(env.fetched, ['u:empty'])
  assert.equal(env.engine.release(), null) // empty 态不再重试
  assert.ok(env.debugEvents.some((entry) => entry.kind === 'clip.empty' && entry.info.url === 'u:empty'))
})

// ---------- 10. idle suspend / resume ----------

test('idle 60s → suspend exactly once; next play resumes before starting (injected clock)', async () => {
  const env = await readyEnv({ clips: { task_finished: 'u:t' } })

  env.setNow(0)
  env.engine.play('task_finished')
  assert.equal(env.ctx().suspendCalls, 0)

  env.setNow(IDLE_SUSPEND_MS - 1)
  env.engine.setVolume('global', 0.5) // 未满 60s → 不挂起
  assert.equal(env.ctx().suspendCalls, 0)

  env.setNow(IDLE_SUSPEND_MS)
  env.engine.setVolume('global', 0.6) // 满 60s → 挂起（节流：只此一次）
  assert.equal(env.ctx().suspendCalls, 1)
  env.engine.setVolume('global', 0.7)
  assert.equal(env.ctx().suspendCalls, 1)

  env.setNow(IDLE_SUSPEND_MS + 500)
  const result = env.engine.play('task_finished')
  assert.equal(result.volume, 0.7)
  assert.equal(env.ctx().resumeCalls, 1)
  // 本次播放的 resume 必须先于它的 start（取最后一次 resume 与其后最近的 start）
  const lastResumeIdx = env.log.map((entry) => entry[0]).lastIndexOf('resume')
  const lastStartIdx = env.log.map((entry) => entry[0]).lastIndexOf('start')
  assert.ok(lastResumeIdx !== -1 && lastStartIdx !== -1 && lastResumeIdx < lastStartIdx)

  env.setNow(2 * IDLE_SUSPEND_MS + 600) // 再空闲 60s → 再次挂起（重新武装）
  env.engine.setVolume('global', 0.8)
  assert.equal(env.ctx().suspendCalls, 2)
})

test('opt-in idle timer fires the suspend; stale timers are neutralized; dispose cancels', async () => {
  const env = makeEnv({ clips: { task_finished: 'u:t' }, captureTimer: true })
  env.engine.warm()
  await env.flush()

  env.setNow(0)
  env.engine.play('task_finished')
  assert.equal(env.timer.count, 1)
  assert.equal(env.timer.ms, IDLE_SUSPEND_MS)

  env.setNow(61_000)
  const firstTimer = env.timer.fn
  firstTimer()
  assert.equal(env.ctx().suspendCalls, 1)

  env.setNow(61_500)
  env.engine.play('task_finished') // resume + 重新武装空闲定时器
  assert.equal(env.timer.count, 2)

  firstTimer() // 旧定时器句柄（序列号已失效）→ 无副作用
  assert.equal(env.ctx().suspendCalls, 1)

  env.setNow(122_000)
  env.timer.fn() // 当前定时器：距 61.5s 已空闲 60.5s → 挂起
  assert.equal(env.ctx().suspendCalls, 2)

  env.engine.dispose()
  env.timer.fn()
  assert.equal(env.ctx().suspendCalls, 2) // dispose 后不再动作
})

// ---------- 11. dispose ----------

test('dispose stops all active + scheduled nodes and makes the engine inert', async () => {
  const env = await readyEnv({ clips: { press: 'u:press', release: 'u:release' } })
  env.ctx().currentTime = 10
  env.engine.press()
  env.engine.release() // future-scheduled source at 10.96
  assert.equal(env.ctx().sources.length, 2)

  env.engine.dispose()
  assert.equal(env.ctx().sources[0].stops, 1)
  assert.equal(env.ctx().sources[1].stops, 1)

  assert.equal(env.engine.press(), null)
  assert.equal(env.engine.play('task_finished'), null)
  assert.equal(env.engine.setVolume('global', 0.1), undefined) // no-op, no throw
  assert.equal(env.ctx().sources.length, 2) // 没有新节点
  assert.equal(env.factoryCalls(), 1)
})

// ---------- 12. preview ----------

test('preview bypasses mute (panel gesture) but respects mapping and volume', async () => {
  const env = await readyEnv({ clips: { press: 'u:press' } })
  env.engine.setMuted(true)

  assert.equal(env.engine.press(), null) // 真实事件被静音拦截
  const result = env.engine.preview('press') // 试听照常
  assert.equal(result.url, 'u:press')
  assert.equal(result.volume, 1)
  assert.equal(env.ctx().sources.length, 1)
})

// ---------- 13. play(event, { at }) scheduling ----------

test('play with { at } schedules at the absolute audio time, clamped to now when past', async () => {
  const env = await readyEnv({ clips: { task_finished: 'u:t' } })
  env.ctx().currentTime = 10

  assert.deepEqual(env.engine.play('task_finished', { at: 12.5 }).when, 12.5)
  assert.deepEqual(env.ctx().sources[0].starts, [12.5])
  assert.deepEqual(env.engine.play('task_finished', { at: 9 }).when, 10) // 排期点已过 → max(now, at)
  assert.deepEqual(env.ctx().sources[1].starts, [10])
})

// ---------- 14. pure helpers ----------

test('pure: computeReleaseStart vectors (splice, long-press clamp, zero duration, custom lead)', () => {
  assert.equal(computeReleaseStart(10, 1.0, 10.2), 10.96) // 短按衔接
  assert.equal(computeReleaseStart(10, 1.0, 11.5), 11.5) // 长按 → 立即
  assert.equal(computeReleaseStart(10, 1.0, 10.96), 10.96) // 恰在排期点
  assert.equal(computeReleaseStart(10, 0, 10.2), 10.2) // 无时长 → 立即
  assert.equal(computeReleaseStart(10, 1.0, 10.2, 0.5), 10.5) // 自定义提前量
  assert.equal(RELEASE_LEAD_SEC, 0.04)
  assert.equal(IDLE_SUSPEND_MS, 60_000)
})

test('pure: resolveVolume tri-state table', () => {
  assert.equal(resolveVolume({}, 0.7, 'press'), 0.7) // 未设 → 全局
  assert.equal(resolveVolume({ question: { vol: 1, volSet: false } }, 0.3, 'question'), 0.3)
  assert.equal(resolveVolume({ question: { vol: 1, volSet: true } }, 0.3, 'question'), 1)
  assert.equal(resolveVolume({ question: { vol: 0.4, volSet: true } }, 0.3, 'approval'), 0.3) // 别的事件的显式值不串
})

test('pure: SOUND_EVENTS covers the five canonical events', () => {
  assert.deepEqual(SOUND_EVENTS, ['press', 'release', 'task_finished', 'question', 'approval'])
})
