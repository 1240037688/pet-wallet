/**
 * WhalePane de-roling (pet-hosting, DR-15 / docs/research/HERMES_PET_SYSTEM.md):
 * the pane no longer renders the self-made whale actor (ui/whale-actor.js
 * retired) — structure = header row (🐋 鲸鱼管家 + mood→accent dot) + bubble
 * layer + data card; the whole panel is the interaction surface feeding the
 * controller (press/release/click = mood machine + bubbles + sound hook).
 */
import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'

register('./loader.mjs', import.meta.url)

const { WhalePane } = await import('../src/ui/whale-pane.js')
const { createWhaleController, $whale, $bubble, moodAccent } = await import('../src/ui/controller.js')

const NULL_ATOM = { get: () => null }

/** Invoke function components (shim useValue = store.get()) and flatten the tree. */
function flatten(vnode) {
  const out = []
  const queue = [vnode]
  while (queue.length) {
    const v = queue.shift()
    if (!v || typeof v !== 'object') continue
    out.push(v)
    let node = v
    if (typeof v.type === 'function') {
      node = v.type(v.props)
      if (!node || typeof node !== 'object') continue
      out.push(node)
    }
    const kids = node.props?.children
    if (Array.isArray(kids)) queue.push(...kids)
    else queue.push(kids)
  }
  return out
}

function renderPane(controller) {
  return WhalePane({
    $balance: NULL_ATOM,
    $summary: NULL_ATOM,
    $dashboard: NULL_ATOM,
    $whale,
    $bubble,
    controller,
  })
}

test('de-roled structure: header row + bubble layer + data card — no whale actor, no SVG face', () => {
  const c = createWhaleController()
  const root = renderPane(c)

  assert.equal(root.type, 'div')
  assert.equal(root.props.className, 'whale-widget-pane')
  assert.equal(root.props.role, 'button')
  assert.equal(root.props.tabIndex, 0)
  assert.equal(root.props.children.length, 3, 'header + bubble layer + data card, nothing else')

  // header row: 🐋 鲸鱼管家 title + mood accent dot; hint explains the pet hosting
  const header = root.props.children[0]
  const headerRendered = header.type(header.props)
  assert.equal(headerRendered.props.className, 'whale-pane-header')
  assert.ok(String(headerRendered.props.title).includes('Hermes 内置宠物'), 'hint names the Hermes pet as the character host')
  assert.ok(String(headerRendered.props.title).includes('随身账本'), 'hint names the pane the pet pocket ledger')
  const [title, dot] = headerRendered.props.children
  assert.equal(title.props.children, '🐋 鲸鱼管家')
  assert.equal(dot.props['data-mood'], $whale.get().mood)
  assert.equal(dot.props.style.background, moodAccent($whale.get().mood))

  // whole flattened tree: zero actor remnants, zero SVG (de-roling hard rule)
  const all = flatten(root)
  assert.ok(all.length > 3, 'tree was actually traversed')
  for (const v of all) {
    assert.ok(!String(v.props?.className ?? '').startsWith('whale-actor'), 'no whale-actor className in the pane')
    assert.notEqual(v.type, 'svg', 'no inline SVG is rendered (no self-made character)')
  }
  assert.ok(all.some((v) => v.props?.children === '余额'), 'data card kept: 余额 row')
  assert.ok(all.some((v) => v.props?.children === '今日'), 'data card kept: 今日 row')
})

test('accent dot follows the mood machine (press blue → waiting amber → idle grey)', () => {
  const c = createWhaleController()
  const dotOf = () => {
    const root = renderPane(c)
    const header = root.props.children[0]
    return header.type(header.props).props.children[1]
  }

  c.press()
  let dot = dotOf()
  assert.equal(dot.props['data-mood'], 'press')
  assert.equal(dot.props.style.background, moodAccent('press'))

  c.release()
  c.syncWaiting({ question: true, approval: false })
  dot = dotOf()
  assert.equal(dot.props['data-mood'], 'waiting')
  assert.equal(dot.props.style.background, '#e8a13a')

  c.syncWaiting({ question: false, approval: false })
  dot = dotOf()
  assert.equal(dot.props['data-mood'], 'idle')
  assert.equal(dot.props.style.background, '#6b7280')
})

test('whole panel is the interaction surface: press/release/click drive the controller', () => {
  const c = createWhaleController()
  const root = renderPane(c)

  root.props.onPointerDown()
  assert.equal($whale.get().mood, 'press')
  root.props.onPointerUp()
  assert.equal($whale.get().mood, 'idle')

  assert.equal(root.props.onClick(), 1, 'click count surfaces from the machine')
  assert.equal($bubble.get()?.key, 'greeting')

  // the queued greeting is actually rendered by the bubble layer inside the pane
  const all = flatten(renderPane(c))
  assert.ok(all.some((v) => v.props?.className === 'whale-bubble'), 'greeting bubble visible in the pane')
})
