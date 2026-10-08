import test from 'node:test'
import assert from 'node:assert/strict'
import { register } from 'node:module'
register('./loader.mjs', import.meta.url)
const { profileBackendView } = await import('../src/ui/dashboard.js')
const { createDataService, $balance, $summary, $dashboard } = await import('../src/core/data-service.js')

test('default-only installation exposes a clear missing-backend state in code', () => {
  assert.equal(profileBackendView({plugins:[{name:'pet-wallet',status:'enabled'}]}, 'default').ready, true)
  const missing = profileBackendView({plugins:[]}, 'code')
  assert.equal(missing.ready, false)
  assert.match(missing.title, /未安装/)
  assert.match(missing.description, /code/)
  assert.match(profileBackendView({plugins:[{key:'pet-wallet',status:'disabled'}]}, 'default').title, /未启用/)
})

for (const [path, atom] of [['/balance', $balance], ['/usage/summary', $summary]]) {
  test(`${path}: late default success cannot populate code data`, async () => {
    let scope = 'default'
    let resolve
    const service = createDataService({getScope:()=>scope,rest:()=>new Promise(r=>{resolve=r})})
    const pending = path === '/balance' ? service._refreshers.refreshBalance() : service._refreshers.refreshSummary()
    scope = 'code'
    atom.set(null)
    $dashboard.set({state:'checking',detail:null})
    resolve({observed_balance_units:100,turns_today:20})
    await pending
    assert.equal(atom.get(), null)
    assert.equal($dashboard.get().state, 'checking')
    service.stop()
  })
}

test('late default failure cannot overwrite new profile status', async () => {
  let scope='default', reject
  const service=createDataService({getScope:()=>scope,rest:()=>new Promise((_,r)=>{reject=r})})
  const pending=service._refreshers.refreshBalance()
  scope='code'
  $dashboard.set({state:'ok',detail:null})
  reject(new Error('old default failure'))
  await pending
  assert.equal($dashboard.get().state,'ok')
  service.stop()
})
