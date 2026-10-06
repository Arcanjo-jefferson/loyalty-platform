import test from 'node:test'
import assert from 'node:assert/strict'
import { createVisitFlow } from '../src/visitFlow.js'
const customer = { customer_id: 'fictional-id', first_name: 'Fictional', last_name: 'Customer' }
const lookup = { customer, total_visits: 4, progress: 4, visits_until_reward: 1, reward_earned: false }
test('keyboard lookup identifies the customer without recording a visit; explicit confirm earns fifth reward', async () => {
  const calls = []
  const flow = createVisitFlow({ request: async (path, options) => {
    calls.push({ path, body: JSON.parse(options.body) })
    return calls.length === 1 ? lookup : { customer, visit: { visit_id: 'fixture' }, total_visits: 5, progress: 0, visits_until_reward: 5, reward_earned: true }
  } })
  await flow.lookup(' fixture-qr-token-123 ')
  assert.equal(flow.getSnapshot().stage, 'ready'); assert.equal(flow.getSnapshot().result.progress, 4)
  assert.deepEqual(calls, [{ path: '/loyalty/lookup', body: { qr_token: 'fixture-qr-token-123' } }])
  await flow.confirm()
  assert.equal(calls[1].path, '/customers/fictional-id/visits'); assert.deepEqual(calls[1].body, {})
  assert.equal(flow.getSnapshot().result.progress, 0); assert.match(flow.getSnapshot().notice, /€10 reward earned/)
  await flow.confirm(); assert.equal(calls.length, 2) // No double confirmation after success.
})
test('unknown/inactive QR, invalid input and edited scan cannot confirm a stale customer', async () => {
  let calls = 0
  const flow = createVisitFlow({ request: async () => { calls++; throw Object.assign(Error('not found'), { status: 404 }) } })
  await flow.confirm(); await flow.lookup('invalid!')
  assert.equal(calls, 0)
  await flow.lookup('unknown-qr-token-123'); await flow.confirm()
  assert.equal(calls, 1); assert.equal(flow.getSnapshot().result, null)
  assert.match(flow.getSnapshot().error, /No active customer/)
  const ready = createVisitFlow({ request: async () => lookup })
  await ready.lookup('fixture-qr-token-123'); ready.clear(); await ready.confirm()
  assert.equal(ready.getSnapshot().result, null)
})
test('failed/duplicate visit stays ready with clear error and no success/reward notice', async () => {
  const flow = createVisitFlow({ request: async path => { if (path === '/loyalty/lookup') return lookup; throw Error('A loyalty visit has already been recorded for this customer today.') } })
  await flow.lookup('fixture-qr-token-123'); await flow.confirm()
  assert.equal(flow.getSnapshot().stage, 'ready'); assert.match(flow.getSnapshot().error, /already been recorded.*today/)
  assert.equal(flow.getSnapshot().notice, '')
  assert.deepEqual(flow.getSnapshot().result, lookup) // No client-side progress increment.
  await flow.lookup('fixture-qr-token-123')
  assert.equal(flow.getSnapshot().result.progress, 4)
  assert.equal(flow.getSnapshot().notice, '')
})
test('simultaneous confirmation clicks send only one write and unmount ignores delayed responses', async () => {
  let writes = 0; let release
  const flow = createVisitFlow({ request: async path => {
    if (path === '/loyalty/lookup') return lookup
    writes++; return new Promise(resolve => { release = resolve })
  } })
  await flow.lookup('fixture-qr-token-123')
  const first = flow.confirm(); await flow.confirm(); assert.equal(writes, 1)
  flow.cancel(); release({ ...lookup, total_visits: 5, reward_earned: true }); await first
  assert.equal(flow.getSnapshot().result, null); assert.equal(flow.getSnapshot().notice, '')
})
test('ordinary visit success updates progress without reward text', async () => {
  const flow = createVisitFlow({ request: async path => path === '/loyalty/lookup' ? { ...lookup, total_visits: 0, progress: 0 } : { ...lookup, total_visits: 1, progress: 1, reward_earned: false } })
  await flow.lookup('fixture-qr-token-123'); await flow.confirm()
  assert.equal(flow.getSnapshot().result.progress, 1)
  assert.equal(flow.getSnapshot().notice, 'Visit recorded successfully.')
})
