import test from 'node:test'
import assert from 'node:assert/strict'
import { createScopedIngestClient } from '../src/core/scoped-ingest-client.js'

const drain = () => new Promise(resolve => setImmediate(resolve))

test('queued default turns stay with default across a switch to code', async () => {
  let scope = 'default'
  const writes = []
  const client = createScopedIngestClient({getScope:()=>scope, rest:async (_, body)=> {
    writes.push({scope, sessions:body.turns.map(turn=>turn.session_id)})
    return {accepted:body.turns.length}
  }})
  client.pause()
  client.submitTurn({session_id:'default-session'})
  scope = 'code'
  client.submitTurn({session_id:'code-session'})
  await client.flushAndWait()
  assert.deepEqual(writes, [{scope:'code',sessions:['code-session']}])
  scope = 'default'
  client.resume()
  await drain()
  assert.deepEqual(writes, [{scope:'code',sessions:['code-session']}, {scope:'default',sessions:['default-session']}])
  client.dispose()
})

test('retry after profile switch never sends old turns to the new profile', async () => {
  let scope='default', release
  const writes=[]
  const client=createScopedIngestClient({getScope:()=>scope, maxRetries:1,
    delay:()=>new Promise(resolve=>{release=resolve}), rest:async (_,body)=> {
      writes.push({scope,session:body.turns[0].session_id})
      throw new Error('temporary outage')
    }})
  client.submitTurn({session_id:'old-session'})
  await drain()
  scope='code'
  client.selectScope()
  release()
  await drain()
  assert.deepEqual(writes,[{scope:'default',session:'old-session'}])
  assert.equal(client.stats().deadLetters,0)
  client.dispose()
})

test('late settlement from default does not publish a cost bubble in code', async () => {
  let scope='default', resolve
  const settlements=[]
  const client=createScopedIngestClient({getScope:()=>scope,
    rest:()=>new Promise(r=>{resolve=r}),onSettled:(rows)=>settlements.push(rows)})
  client.submitTurn({session_id:'old-session'})
  await drain()
  scope='code'
  client.selectScope()
  resolve({settled:[{estimated_cost_units:123}]})
  await drain()
  assert.deepEqual(settlements,[])
  client.dispose()
})
