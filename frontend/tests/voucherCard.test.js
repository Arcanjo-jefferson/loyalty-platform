import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import VoucherCard from '../src/components/VoucherCard.js'
import { createVoucherFlow } from '../src/voucherFlow.js'
const voucher = { voucher_id: 'fixture-voucher', customer_id: 'fixture-customer', voucher_code: 'ABCDE-FGHJK-LMNPQ-RSTUV', type: 'LOYALTY_10', value_cents: 1000, status: 'ACTIVE', issued_at: '2026-10-07T12:00:00Z', expires_at: '2026-10-07T23:00:00Z' }
const render = item => renderToStaticMarkup(createElement(VoucherCard, { voucher: item, busy: false, onRedeem: () => {} }))

test('ACTIVE voucher renders the redemption button', () => {
  assert.match(render(voucher), /<button[^>]*>Redeem voucher<\/button>/)
})
test('REDEEMED voucher shows a non-interactive state and redeemed timestamp', () => {
  const html = render({ ...voucher, status: 'REDEEMED', redeemed_at: '2026-10-07T13:00:00Z' })
  assert.doesNotMatch(html, /Redeem voucher|<button/)
  assert.match(html, /voucher-state-redeemed/)
  assert.match(html, /✓/)
  assert.match(html, /<dt>Redeemed<\/dt>/)
  assert.match(html, /14:00:00/)
})
test('EXPIRED voucher shows Expired and no redemption button', () => {
  const html = render({ ...voucher, status: 'EXPIRED' })
  assert.doesNotMatch(html, /Redeem voucher|<button/)
  assert.match(html, /class="voucher-state">Expired/)
})
test('customer profile card directly redeems without code lookup or navigation', async () => {
  const calls = []
  const flow = createVoucherFlow({ clock: () => Date.parse('2026-10-07T13:00:00Z'), request: async (path, options) => {
    calls.push({ path, options }); return options?.method === 'POST' ? { ...voucher, status: 'REDEEMED', redeemed_at: '2026-10-07T13:00:00Z' } : [voucher]
  } })
  await flow.load(voucher.customer_id)
  const card = VoucherCard({ voucher: flow.getSnapshot().vouchers[0], busy: false, onRedeem: item => flow.redeem(item) })
  const button = card.props.children.find(child => child?.type === 'button')
  await button.props.onClick()
  assert.deepEqual(calls.map(c => c.path), ['/customers/fixture-customer/vouchers', '/customers/fixture-customer/vouchers/fixture-voucher/redeem'])
  assert.equal(calls[1].options.body, '{}')
  assert.doesNotMatch(render(flow.getSnapshot().vouchers[0]), /Redeem voucher/)
})
test('standalone code lookup returns the same status-aware voucher card', async () => {
  const calls = []
  const flow = createVoucherFlow({ clock: () => Date.parse('2026-10-07T13:00:00Z'), request: async (path, options) => { calls.push({ path, body: JSON.parse(options.body) }); return voucher } })
  await flow.lookup(voucher.voucher_code)
  assert.deepEqual(calls, [{ path: '/vouchers/lookup', body: { voucher_code: voucher.voucher_code } }])
  assert.match(render(flow.getSnapshot().vouchers[0]), /Redeem voucher/)
})
