/**
 * Sound engine — Web Audio (M9). DSH §E1 discipline, engine core only
 * (wiring into main.js happens in a later integration step).
 *
 *   - AudioBufferSourceNode + GainNode only (never an <audio> media element,
 *     so OS media controls / TouchBar never pick the sounds up);
 *   - URL-level cache: one fetch + one decodeAudioData per URL, shared across
 *     events. Empty (204-style) responses and decode failures are CACHED as
 *     terminal states and never retried (reported via onDebug, never thrown);
 *   - synchronous start path: press()/release()/play()/preview() NEVER await
 *     the decode promise — a clip that is not ready yet skips that one play
 *     while the decode continues in the background (warm() after the unlock
 *     gesture makes the first press hit the ready path);
 *   - audio-thread scheduling: start(when) uses the AudioContext clock; the
 *     release sound is scheduled at pressStart + pressDuration − 40ms
 *     (RELEASE_LEAD_SEC), clamped to now — the seamless short-press splice
 *     that is immune to main-thread jitter;
 *   - AudioContext lifecycle: created lazily on the first unmuted play/warm,
 *     NEVER closed (task-end sounds are not gesture-triggered — a closed
 *     context could never play them), suspended after IDLE_SUSPEND_MS without
 *     activity and resumed before the next play;
 *   - volume tri-state: every event kind has its own slot { vol, volSet };
 *     volSet=false (slider never explicitly dragged) → follow the global
 *     press volume; explicit set → use its own value; mute overrides
 *     everything (and a muted engine builds no context at all);
 *   - sound group (minimal): while a group is active its slots override the
 *     base clip mapping; an empty-string slot means that event is silent
 *     (no fallback to the base mapping), an absent slot falls through.
 *
 * EVERY Web Audio object is created through the injected contextFactory —
 * tests run against a fake context and never touch a real audio device.
 * Wall-clock time is injected for deterministic idle-suspend tests; the
 * proactive 60s idle timer is strictly opt-in (setTimer) so node tests never
 * leave dangling timers — without it the suspend is still enforced lazily on
 * the next engine call.
 */

export const RELEASE_LEAD_SEC = 0.04
export const IDLE_SUSPEND_MS = 60_000
export const SOUND_EVENTS = ['press', 'release', 'task_finished', 'question', 'approval']

/** 默认映射：全部 null = 无声（结构先立，clip 由集成层注入）。 */
export const DEFAULT_CLIPS = Object.freeze(
  Object.fromEntries(SOUND_EVENTS.map((event) => [event, null])),
)

/** Clamp to [0, 1]; non-numeric → null (caller keeps the previous value). */
export function clampVolume(value) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.min(1, Math.max(0, value))
}

/**
 * Pure: effective volume for an event kind (mute is handled at playback
 * level — it suppresses playing entirely, it is not a volume).
 * volSet=false → follow the global press volume (默认 100% ≠ 设了 100%).
 */
export function resolveVolume(eventVols, globalVol, kind) {
  const slot = eventVols[kind]
  if (slot && slot.volSet) return slot.vol
  return globalVol
}

/**
 * Pure: absolute audio-clock time for the release sound.
 * Short press → seamless splice at pressStart + pressDuration − lead.
 * Long press (that moment already passed) → start now (max clamp).
 */
export function computeReleaseStart(pressStartedAt, pressDuration, currentTime, leadSec = RELEASE_LEAD_SEC) {
  return Math.max(currentTime, pressStartedAt + (pressDuration || 0) - leadSec)
}

/**
 * @param {object} options
 * @param {Function} options.contextFactory  ({ latencyHint }) → AudioContext-like (all nodes come from it)
 * @param {Function} [options.now]           wall clock in ms (idle-suspend measurement; default Date.now)
 * @param {Function} [options.fetchClip]     url → Promise<encodedData|null>; null = empty response (204-style)
 * @param {Function} [options.onDebug]       (kind, info) debug-log-style callback; failures never throw
 * @param {Function} [options.setTimer]      (fn, ms) → handle; opt-in proactive idle timer (stale handles
 *                                           are neutralized by sequence number — no clearTimer needed)
 */
export function createSoundEngine({
  contextFactory,
  now = () => Date.now(),
  fetchClip = null,
  onDebug = null,
  setTimer = null,
} = {}) {
  let disposed = false
  let muted = false
  let ctx = null
  let ctxBroken = false
  let globalVol = 1
  const eventVols = {} // kind → { vol, volSet }
  const baseClips = { ...DEFAULT_CLIPS }
  let group = null // { id, clips } — active sound group (minimal)
  const cache = new Map() // url → { state: loading|ready|failed|empty|pending, buffer, data }
  let pressAnchor = null // { startedAt, duration } — set by press(), consumed by release()
  let lastActivityAt = null
  let idleSuspended = false
  let idleSeq = 0
  const activeNodes = new Set() // { source, gain } — stopped on mute/dispose

  function debug(kind, info) {
    if (typeof onDebug !== 'function') return
    try {
      onDebug(kind, info || {})
    } catch {
      /* a debug callback must never break playback */
    }
  }

  function errorMessage(error) {
    const message = error && error.message ? error.message : String(error)
    return message.slice(0, 200)
  }

  function nowMs() {
    return typeof now === 'function' ? now() : 0
  }

  function touch() {
    lastActivityAt = nowMs()
    scheduleIdleCheck()
  }

  function scheduleIdleCheck() {
    if (typeof setTimer !== 'function') return
    idleSeq += 1
    const seq = idleSeq
    setTimer(() => {
      if (disposed || seq !== idleSeq) return
      maybeIdleSuspend()
      if (!idleSuspended) scheduleIdleCheck()
    }, IDLE_SUSPEND_MS)
  }

  function cancelIdleCheck() {
    idleSeq += 1
  }

  function maybeIdleSuspend() {
    if (!ctx || idleSuspended || disposed) return
    if (lastActivityAt === null || nowMs() - lastActivityAt < IDLE_SUSPEND_MS) return
    try {
      ctx.suspend()
    } catch (error) {
      debug('context.suspend.failed', { message: errorMessage(error) })
      return
    }
    idleSuspended = true
  }

  function ensureContext() {
    if (ctx) return ctx
    if (ctxBroken) return null
    if (typeof contextFactory !== 'function') {
      ctxBroken = true
      debug('context.factory.missing')
      return null
    }
    try {
      ctx = contextFactory({ latencyHint: 'interactive' })
    } catch (error) {
      ctxBroken = true
      debug('context.create.failed', { message: errorMessage(error) })
      return null
    }
    if (!ctx) {
      ctxBroken = true
      debug('context.create.failed', { message: 'factory returned falsy' })
      return null
    }
    return ctx
  }

  function resumeIfSuspended(context) {
    if (!idleSuspended && context.state !== 'suspended') return
    try {
      context.resume()
    } catch (error) {
      debug('context.resume.failed', { message: errorMessage(error) })
    }
    idleSuspended = false
  }

  function isClipValue(value) {
    return typeof value === 'string' && value !== ''
  }

  function resolveClipUrl(event) {
    if (group && group.clips && Object.prototype.hasOwnProperty.call(group.clips, event)) {
      // 组槽位留空 = 该事件静音，不回退预设（DSH E1）
      const value = group.clips[event]
      return isClipValue(value) ? value : null
    }
    const value = baseClips[event]
    return isClipValue(value) ? value : null
  }

  function ensureClip(url) {
    const cached = cache.get(url)
    if (cached) return cached
    const entry = { state: 'loading', buffer: null, data: null }
    cache.set(url, entry)
    if (typeof fetchClip !== 'function') {
      entry.state = 'empty'
      debug('clip.no_fetcher', { url })
      return entry
    }
    Promise.resolve()
      .then(() => fetchClip(url))
      .then((data) => {
        if (disposed) return
        if (data === null || data === undefined) {
          // DSH: 204/0-byte is intercepted here — handed to decodeAudioData it
          // would reject with EncodingError; explicit empty = silence.
          entry.state = 'empty'
          debug('clip.empty', { url })
          return
        }
        if (muted) {
          // A muted engine must not build a context: hold the bytes, decode on unmute.
          entry.state = 'pending'
          entry.data = data
          return
        }
        decodeEntry(entry, url, data)
      })
      .catch((error) => {
        entry.state = 'failed'
        entry.data = null
        debug('clip.decode.failed', { url, message: errorMessage(error) })
      })
    return entry
  }

  function decodeEntry(entry, url, data) {
    const context = ensureContext()
    if (!context) {
      entry.state = 'failed'
      entry.data = null
      debug('clip.decode.failed', { url, message: 'no audio context' })
      return
    }
    Promise.resolve(context.decodeAudioData(data))
      .then((buffer) => {
        entry.state = 'ready'
        entry.buffer = buffer
        entry.data = null
      })
      .catch((error) => {
        // 失败态缓存：同 URL 不再重试，不 throw（DSH: EncodingError → 静音）
        entry.state = 'failed'
        entry.data = null
        debug('clip.decode.failed', { url, message: errorMessage(error) })
      })
  }

  function bufferDuration(buffer) {
    const duration = Number(buffer && buffer.duration)
    return Number.isFinite(duration) && duration > 0 ? duration : 0
  }

  function trackNode(source, gain) {
    const node = { source, gain }
    activeNodes.add(node)
    try {
      source.onended = () => {
        activeNodes.delete(node)
        try {
          gain.disconnect()
        } catch {
          /* already disconnected */
        }
      }
    } catch {
      /* non-fatal */
    }
  }

  function stopActiveNodes() {
    for (const node of activeNodes) {
      try {
        node.source.stop()
      } catch {
        /* already stopped */
      }
      try {
        node.gain.disconnect()
      } catch {
        /* already disconnected */
      }
    }
    activeNodes.clear()
  }

  /**
   * Core playback path. Synchronous — never awaits a decode promise.
   * Returns { url, when, volume, duration } or null (nothing played).
   */
  function playEvent(event, { at = null, ignoreMute = false } = {}) {
    if (disposed) return null
    maybeIdleSuspend()
    if (muted && !ignoreMute) return null
    touch()
    const url = resolveClipUrl(event)
    if (!url) return null
    const context = ensureContext()
    if (!context) return null
    resumeIfSuspended(context)
    const entry = ensureClip(url)
    if (entry.state !== 'ready' || !entry.buffer) return null // 未就绪跳过本次；后台继续解码缓存
    const volume = resolveVolume(eventVols, globalVol, event)
    let source = null
    let gain = null
    try {
      source = context.createBufferSource()
      source.buffer = entry.buffer
      gain = context.createGain()
      gain.gain.value = volume
      source.connect(gain)
      gain.connect(context.destination)
    } catch (error) {
      debug('node.create.failed', { event, message: errorMessage(error) })
      return null
    }
    const when =
      typeof at === 'number' && Number.isFinite(at)
        ? Math.max(context.currentTime, at) // 排期点已过 → 立即（取 max(now, 排期点)）
        : context.currentTime
    try {
      source.start(when)
    } catch (error) {
      debug('start.failed', { event, message: errorMessage(error) })
      return null
    }
    trackNode(source, gain)
    return { url, when, volume, duration: bufferDuration(entry.buffer) }
  }

  /** 按下：立即同步起播；成功时记下按压锚点供 release() 精确衔接。 */
  function press() {
    const result = playEvent('press')
    pressAnchor = result ? { startedAt: result.when, duration: result.duration } : null
    return result
  }

  /** 松开：把松开音排期到「按压音剩余时长 − 40ms」处（绝对音频时刻，取 max(now, ·)）。 */
  function release() {
    if (disposed) return null
    const anchor = pressAnchor
    pressAnchor = null
    let at = null
    if (anchor && ctx) {
      at = computeReleaseStart(anchor.startedAt, anchor.duration, ctx.currentTime)
    }
    return playEvent('release', { at })
  }

  /** 一次性事件音（task_finished / question / approval…）。at = 绝对音频时刻（可选）。 */
  function play(event, options = {}) {
    return playEvent(event, options)
  }

  /** 试听：设置面板的用户手势，绕过总静音（仍遵循 clip 映射与音量解析）。 */
  function preview(event) {
    return playEvent(event, { ignoreMute: true })
  }

  /**
   * kind='global' → 全局基准（按压音量）；kind=事件名 → 该事件音量。
   * explicit=true 仅在用户显式拖过滑块时传 —— 区分「默认 100%」与「设了 100%」。
   */
  function setVolume(kind, value, { explicit = false } = {}) {
    if (disposed) return
    maybeIdleSuspend()
    const volume = clampVolume(value)
    if (volume === null) return
    if (kind === 'global') {
      globalVol = volume
      return
    }
    if (typeof kind !== 'string' || kind === '') return
    let slot = eventVols[kind]
    if (!slot) {
      slot = { vol: 1, volSet: false }
      eventVols[kind] = slot
    }
    slot.vol = volume
    if (explicit) slot.volSet = true
  }

  /** 总开关：最高优先级。静音时不建 context、不取流；并停掉正在播/已排期的节点。 */
  function setMuted(value) {
    if (disposed) return
    const nextMuted = !!value
    if (nextMuted === muted) return
    muted = nextMuted
    if (nextMuted) {
      pressAnchor = null
      stopActiveNodes()
      return
    }
    // 解除静音：补解码静音期间到达的片段（此时才允许建 context）
    for (const [url, entry] of cache) {
      if (entry.state !== 'pending') continue
      entry.state = 'loading'
      const data = entry.data
      entry.data = null
      decodeEntry(entry, url, data)
    }
  }

  /** 事件 → clip URL（''/null = 该事件静音）。不自动取流 —— 集成层在手势后调 warm()。 */
  function setClip(event, url) {
    if (disposed) return
    baseClips[event] = isClipValue(url) ? url : null
  }

  function setClips(map) {
    if (disposed || !map || typeof map !== 'object') return
    for (const event of Object.keys(map)) setClip(event, map[event])
  }

  /** 音效组（最小实现）：激活期间组槽位覆盖基础映射；空槽位 = 静音；缺省槽位回退基础映射。 */
  function setSoundGroup(next) {
    if (disposed) return
    if (!next) {
      group = null
      return
    }
    const clips = next.clips && typeof next.clips === 'object' ? { ...next.clips } : {}
    group = { id: typeof next.id === 'string' ? next.id : null, clips }
  }

  function collectMappedUrls() {
    const urls = new Set()
    for (const value of Object.values(baseClips)) if (isClipValue(value)) urls.add(value)
    if (group && group.clips) {
      for (const value of Object.values(group.clips)) if (isClipValue(value)) urls.add(value)
    }
    return Array.from(urls)
  }

  /** 预取 + 预解码（解锁手势后调用）。返回仍在解码中的 url 列表。 */
  function warm(urls = null) {
    if (disposed || muted) return []
    const list = urls === null ? collectMappedUrls() : Array.isArray(urls) ? urls : [urls]
    const warming = []
    for (const url of list) {
      if (!isClipValue(url)) continue
      const entry = ensureClip(url)
      if (entry.state === 'loading') warming.push(url)
    }
    return warming
  }

  /** 卸载：停掉全部节点、取消空闲定时器。绝不 close context（DSH：任务结束音非手势触发）。 */
  function dispose() {
    if (disposed) return
    disposed = true
    cancelIdleCheck()
    pressAnchor = null
    stopActiveNodes()
    ctx = null
  }

  return {
    press,
    release,
    play,
    preview,
    setVolume,
    setMuted,
    setClip,
    setClips,
    setSoundGroup,
    warm,
    dispose,
  }
}
