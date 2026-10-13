import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { normalizeIrishMobile } from '../src/validation.js'
import { searchCustomers } from '../src/customerSearch.js'
import { customerQRLink, publicQRReference, createQRFlow } from '../src/qrFlow.js'
import PublicQRView from '../src/components/PublicQRView.js'
const reference = 'a'.repeat(43)
const info = { qr_token: 'opaque-existing-token', public_reference: reference }

test('customer search finds first/last/full names and equivalent Irish phones', () => {
  const customer = { customer_id: 'fixture', first_name: 'Fictional', last_name: 'Customer', phone: '+353871234567' }
  for (const query of ['fictional', 'Customer', 'Fictional Customer', '  fictional   customer ', '0871234567', '+353871234567', '087 123 4567']) assert.deepEqual(searchCustomers([customer], query), [customer])
  assert.deepEqual(searchCustomers([customer], 'other'), [])
})
test('public link is opaque and contains no business, customer UUID or PII', () => {
  const url = customerQRLink(reference, 'https://customer.example')
  assert.equal(url, `https://customer.example/q/${reference}`)
  assert.equal(publicQRReference(new URL(url).pathname), reference)
  assert.equal(publicQRReference('/q/customer-id'), null)
  assert.throws(() => customerQRLink('tenant/customer', 'https://customer.example'))
  assert.throws(() => customerQRLink(reference, 'javascript:alert(1)'))
})
test('public render contains only generic branding, QR and instructions', () => {
  const html = renderToStaticMarkup(createElement(PublicQRView, { imageUrl: `https://api.example/public/qr/${reference}/image`, loaded: true, failed: false }))
  assert.match(html, /Loyalty System/); assert.match(html, /loyalty-qr-image/)
  assert.doesNotMatch(html, /first_name|date_of_birth|voucher|visit_id|customer_id|phone|address/)
  const unavailable = renderToStaticMarkup(createElement(PublicQRView, { failed: true }))
  assert.match(unavailable, /unavailable/); assert.doesNotMatch(unavailable, /<img/)
})
test('recovery retains existing link and regeneration requires explicit confirmation', async () => {
  const calls = []
  const flow = createQRFlow({ request: async (path, options) => { calls.push({ path, body: JSON.parse(options.body) }); return info } })
  await flow.load('fixture'); await flow.regenerate('fixture', false)
  assert.equal(calls.length, 1)
  assert.equal(customerQRLink(flow.getSnapshot().details.public_reference, 'https://example.test'), `https://example.test/q/${reference}`)
  await flow.regenerate('fixture', true)
  assert.deepEqual(calls[1], { path: '/customers/fixture/qr/regenerate', body: { confirmed: true, expected_qr_token: info.qr_token } })
})
test('failed regeneration and unavailable SMS never claim success', async () => {
  const flow = createQRFlow({ request: async path => { if (path.endsWith('/link')) return info; throw Error('SMS sending is not configured yet.') } })
  await flow.load('fixture'); await flow.regenerate('fixture', true)
  assert.equal(flow.getSnapshot().details, info); assert.equal(flow.getSnapshot().notice, '')
  await flow.send('fixture'); assert.match(flow.getSnapshot().error, /not configured/); assert.equal(flow.getSnapshot().notice, '')
})
test('actual profile and public entry paths use QR components without exposing raw tokens', () => {
  const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  assert.match(source('../src/components/CustomerProfile.jsx'), /<CustomerQR/)
  assert.match(source('../src/main.jsx'), /pathname.startsWith\('\/q\/'\) \? <PublicQR/)
  const component = source('../src/components/CustomerQR.jsx')
  assert.match(component, /Copy QR Link/); assert.match(component, /Confirm regeneration/)
  assert.match(component, /\['OWNER', 'MANAGER'\].includes\(user.role\)/)
  assert.match(component, /URL.revokeObjectURL/)
  assert.doesNotMatch(component, /\{customer.qr_token\}/)
})


test('search-only normalization matches all four Irish representations to the same customer', () => {
  const customer = { customer_id: 'fictional-mobile', first_name: 'Test', last_name: 'Person', phone: '+353831234567' }
  const other = { customer_id: 'other-mobile', first_name: 'Another', last_name: 'Person', phone: '+353871234567' }
  for (const query of ['0831234567', '831234567', '+353831234567', '353831234567', '083 123 4567', '353 83 123 4567']) {
    assert.deepEqual(searchCustomers([customer, other], query), [customer], query)
  }
  // The search tolerance must not make registration/update validation permissive.
  assert.equal(normalizeIrishMobile('831234567'), null)
  assert.equal(normalizeIrishMobile('353831234567'), null)
})

test('partial phone search retains sensible national and international prefix matches', () => {
  const customer = { customer_id: 'fictional-mobile', first_name: 'Test', last_name: 'Person', phone: '+353831234567' }
  for (const query of ['083', '083123', '83123', '+35383', '35383', '234567']) {
    assert.deepEqual(searchCustomers([customer], query), [customer], query)
  }
  assert.deepEqual(searchCustomers([customer], '083999'), [])
})
