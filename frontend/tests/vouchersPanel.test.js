import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import VouchersPanel from '../src/components/VouchersPanel.js'
const voucher = { voucher_id: 'fixture', customer_id: 'customer', type: 'LOYALTY_10', value_cents: 1000, expires_at: '2026-10-08T23:00:00Z', redeemed_at: '2026-10-07T12:00:00Z' }
for (const customerId of ['customer', undefined]) {
  for (const status of ['ACTIVE', 'REDEEMED', 'EXPIRED', ' redeemed ', 'expired']) {
    test(`${customerId ? 'profile' : 'standalone'} full panel renders ${status} from backend status`, () => {
      const html = renderToStaticMarkup(createElement(VouchersPanel, { customerId, code: 'fixture', now: Date.parse('2026-10-07T13:00:00Z'), state: { vouchers: [{ ...voucher, status }], loaded: true, busy: false }, onRedeem() {} }))
      assert.match(html, /class="vouchers-content"/)
      assert.match(html, customerId ? /Refresh vouchers/ : /Voucher code.*Look up voucher/)
      if (status.trim().toUpperCase() === 'ACTIVE') assert.match(html, /Redeem voucher/)
      else { assert.doesNotMatch(html, /Redeem voucher/); assert.match(html, status.toUpperCase().includes('REDEEMED') ? /voucher-state-redeemed/ : />Expired</) }
    })
  }
}
test('both actual route wrappers import the single voucher component and its local padding stylesheet', () => {
  const read = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  assert.match(read('../src/App.jsx'), /page === 'vouchers' && <Vouchers/)
  assert.match(read('../src/components/CustomerProfile.jsx'), /<Vouchers.*customerId={customer.customer_id}/)
  const wrapper = read('../src/components/Vouchers.jsx')
  assert.match(wrapper, /import '\.\/Vouchers.css'/)
  assert.match(wrapper, /return <VouchersPanel/)
  assert.doesNotMatch(wrapper, /Redeem voucher/)
  assert.match(read('../src/components/VouchersPanel.js'), /h\(VoucherCard/)
  assert.match(read('../src/components/Vouchers.css'), /\.panel\.vouchers > \.vouchers-content { padding: 25px; }/)
})
