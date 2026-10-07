import test from 'node:test'
import assert from 'node:assert/strict'
import { createVoucherFlow, effectiveVoucher, rewardMessages, voucherLabel } from '../src/voucherFlow.js'
import { createAuthenticatedClient } from '../src/httpClient.js'
import { createVisitFlow } from '../src/visitFlow.js'
const now = Date.parse('2026-10-07T13:00:00Z')
const voucher = { voucher_id: 'fictional-voucher', customer_id: 'fictional-customer', voucher_code: 'ABCDE-FGHJK-LMNPQ-RSTUV', type: 'LOYALTY_10', value_cents: 1000, status: 'ACTIVE', expires_at: '2026-10-07T23:00:00Z' }

test('loyalty, birthday and both visit rewards display separately and only on success', async () => {
  for (const vouchers of [[voucher], [{ ...voucher, type: 'BIRTHDAY_20' }], [voucher, { ...voucher, type: 'BIRTHDAY_20' }]]) {
    const customer = { customer_id: 'fictional-customer' }
    const flow = createVisitFlow({ request: async path => path === '/loyalty/lookup' ? { customer } : { customer, vouchers, progress: 0 } })
    await flow.lookup('fixture-qr-token-123'); assert.equal(flow.getSnapshot().notice, '')
    await flow.confirm()
    for (const message of rewardMessages(vouchers)) assert.ok(flow.getSnapshot().notice.includes(message))
    assert.equal(rewardMessages(vouchers).length, vouchers.length)
  }
  assert.equal(voucherLabel(voucher), '€10 Loyalty Voucher')
  assert.equal(voucherLabel({ type: 'BIRTHDAY_20' }), '€20 Birthday Voucher')
})

test('customer voucher listing uses authenticated transport and effective expiry', async () => {
  const calls = []
  const flow = createVoucherFlow({ clock: () => now, request: async (path, options) => { calls.push({ path, options }); return [voucher, { ...voucher, voucher_id: 'expired', expires_at: '2026-10-06T23:00:00Z' }] } })
  await flow.load('fictional-customer')
  assert.equal(calls[0].path, '/customers/fictional-customer/vouchers')
  assert.equal(calls[0].options.cache, 'no-store')
  assert.equal(flow.getSnapshot().vouchers[0].status, 'ACTIVE')
  assert.equal(flow.getSnapshot().vouchers[1].status, 'EXPIRED')
  assert.equal(effectiveVoucher(voucher, Date.parse(voucher.expires_at)).status, 'EXPIRED')
  assert.equal(effectiveVoucher({ ...voucher, status: 'REDEEMED' }, Infinity).status, 'REDEEMED')
})

test('lookup and successful redemption send no caller identity or tenant', async () => {
  const calls = []
  const flow = createVoucherFlow({ clock: () => now, request: async (path, options) => { calls.push({ path, body: JSON.parse(options.body) }); return path.endsWith('lookup') ? voucher : { ...voucher, status: 'REDEEMED', redeemed_at: '2026-10-07T13:00:00Z' } } })
  await flow.lookup('  '+voucher.voucher_code+'  ')
  assert.deepEqual(calls[0].body, { voucher_code: voucher.voucher_code })
  await flow.redeem(flow.getSnapshot().vouchers[0])
  assert.deepEqual(calls[1], { path: '/customers/fictional-customer/vouchers/fictional-voucher/redeem', body: {} })
  assert.equal(flow.getSnapshot().vouchers[0].status, 'REDEEMED')
  assert.equal(flow.getSnapshot().notice, 'Voucher redeemed successfully.')
})

test('expired and already redeemed vouchers cannot be submitted for redemption', async () => {
  for (const item of [{ ...voucher, expires_at: '2026-10-06T23:00:00Z' }, { ...voucher, status: 'REDEEMED' }]) {
    let calls = 0
    const flow = createVoucherFlow({ clock: () => now, request: async () => { calls++; return item } })
    await flow.lookup(voucher.voucher_code); await flow.redeem(item)
    assert.equal(calls, 1); assert.match(flow.getSnapshot().error, /expired or.*redeemed/)
    assert.equal(flow.getSnapshot().notice, '')
  }
})

test('server redemption conflict refreshes status without showing success', async () => {
  let lookups = 0
  const flow = createVoucherFlow({ clock: () => now, request: async path => {
    if (path.endsWith('lookup')) return lookups++ ? { ...voucher, status: 'REDEEMED' } : voucher
    throw Object.assign(Error('This voucher has expired or has already been redeemed.'), { status: 409 })
  } })
  await flow.lookup(voucher.voucher_code); await flow.redeem(voucher)
  assert.equal(flow.getSnapshot().vouchers[0].status, 'REDEEMED')
  assert.equal(flow.getSnapshot().notice, ''); assert.match(flow.getSnapshot().error, /already been redeemed/)
})

test('API lookup/list/redemption failures keep clear errors and never success', async () => {
  for (const operation of ['lookup', 'load']) {
    const flow = createVoucherFlow({ request: async () => { throw Error('Voucher not found.') } })
    await flow[operation]('fixture')
    assert.equal(flow.getSnapshot().error, 'Voucher not found.')
    assert.equal(flow.getSnapshot().notice, ''); assert.deepEqual(flow.getSnapshot().vouchers, [])
  }
  const flow = createVoucherFlow({ clock: () => now, request: async path => { if (path.endsWith('lookup')) return voucher; throw Error('Failed to fetch') } })
  await flow.lookup(voucher.voucher_code); await flow.redeem(voucher)
  assert.match(flow.getSnapshot().error, /Check the voucher status/)
  assert.equal(flow.getSnapshot().notice, '')
})

test('double redemption clicks only make one request; unmount ignores late response', async () => {
  let resolve; let writes = 0
  const flow = createVoucherFlow({ clock: () => now, request: async path => { if (path.endsWith('lookup')) return voucher; writes++; return new Promise(done => { resolve = done }) } })
  await flow.lookup(voucher.voucher_code)
  const pending = flow.redeem(voucher); await flow.redeem(voucher)
  assert.equal(writes, 1)
  flow.cancel(); resolve({ ...voucher, status: 'REDEEMED' }); await pending
  assert.equal(flow.getSnapshot().notice, ''); assert.deepEqual(flow.getSnapshot().vouchers, [])
})


test('voucher reads and redemption require the existing bearer authentication', async () => {
  let calls = 0
  const request = createAuthenticatedClient({ base: '', getToken: async () => { throw Error('No authenticated ID token') }, onExpired: () => {}, fetchRequest: async () => { calls++; assert.fail('Anonymous request') } })
  const flow = createVoucherFlow({ request, clock: () => now })
  await flow.lookup(voucher.voucher_code); assert.match(flow.getSnapshot().error, /session has expired/)
  await flow.load(voucher.customer_id); assert.match(flow.getSnapshot().error, /session has expired/)
  await flow.redeem(voucher); assert.match(flow.getSnapshot().error, /session has expired/)
  assert.equal(calls, 0); assert.equal(flow.getSnapshot().notice, '')
  let signedIn = true
  const activeRequest = createAuthenticatedClient({ base: '', getToken: async () => { if (!signedIn) throw Error('Session ended'); return 'fixture-id-token' }, onExpired: () => {}, fetchRequest: async () => { calls++; return { status: 200, ok: true, json: async () => voucher } } })
  const activeFlow = createVoucherFlow({ request: activeRequest, clock: () => now })
  await activeFlow.lookup(voucher.voucher_code); signedIn = false
  await activeFlow.redeem(voucher)
  assert.equal(calls, 1); assert.match(activeFlow.getSnapshot().error, /session has expired/)
  assert.equal(activeFlow.getSnapshot().notice, '')
})


test('editing the lookup code clears the previous voucher and prevents stale redemption', async () => {
  let calls = 0
  const flow = createVoucherFlow({ clock: () => now, request: async () => { calls++; return voucher } })
  await flow.lookup(voucher.voucher_code); flow.clear(); await flow.redeem(voucher)
  assert.equal(calls, 1); assert.deepEqual(flow.getSnapshot().vouchers, [])
})
