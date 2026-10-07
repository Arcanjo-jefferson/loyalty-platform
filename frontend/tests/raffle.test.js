import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { createVisitFlow } from '../src/visitFlow.js'
import { createRaffleHistory, visitSuccessMessages } from '../src/raffleFlow.js'
import CustomerRaffleView from '../src/components/CustomerRaffleView.js'
import { createAuthenticatedClient } from '../src/httpClient.js'

const customer = { customer_id: 'fictional-customer', first_name: 'Fictional', last_name: 'Person' }
const entry = { raffle_entry_id: 'random-visit-id', visit_id: 'random-visit-id', customer_id: customer.customer_id,
  raffle_date: '2026-10-07', created_at: '2026-10-06T23:05:00Z', visit_number: 1 }
const lookup = { customer, total_visits: 0, progress: 0, vouchers: [] }

test('confirmed visit shows raffle and each earned reward separately, based on backend response', async () => {
  for (const vouchers of [[], [{ type: 'LOYALTY_10' }], [{ type: 'BIRTHDAY_20' }], [{ type: 'LOYALTY_10' }, { type: 'BIRTHDAY_20' }]]) {
    const result = { ...lookup, raffle_entry: entry, vouchers, total_visits: 1, progress: 1 }
    const calls = []
    const flow = createVisitFlow({ request: async path => { calls.push(path); return path === '/loyalty/lookup' ? lookup : result } })
    await flow.lookup('fixture-qr-token-123')
    assert.equal(flow.getSnapshot().notice, '')
    assert.deepEqual(calls, ['/loyalty/lookup'])
    await flow.confirm()
    assert.equal(calls.length, 2)
    assert.match(flow.getSnapshot().notice, /Visit recorded successfully.*Daily Raffle entry created/)
    const messages = visitSuccessMessages(result)
    assert.equal(messages.length, 2 + vouchers.length)
    assert.equal(messages.filter(message => message.includes('Daily Raffle')).length, 1)
    assert.equal(messages.some(message => message.includes('€10')), vouchers.some(voucher => voucher.type === 'LOYALTY_10'))
    assert.equal(messages.some(message => message.includes('€20')), vouchers.some(voucher => voucher.type === 'BIRTHDAY_20'))
    await flow.confirm(); assert.equal(calls.length, 2)
  }
  assert.equal(visitSuccessMessages(lookup).some(message => message.includes('Raffle')), false)
})

test('duplicate/failed confirmation never displays raffle success or increments progress', async () => {
  for (const message of ['A loyalty visit has already been recorded for this customer today.', 'Customer storage is temporarily unavailable.']) {
    const flow = createVisitFlow({ request: async path => { if (path === '/loyalty/lookup') return lookup; throw Error(message) } })
    await flow.lookup('fixture-qr-token-123'); await flow.confirm()
    assert.equal(flow.getSnapshot().notice, '')
    assert.equal(flow.getSnapshot().result, lookup)
    assert.equal(flow.getSnapshot().error, message)
  }
})

test('raffle history uses the customer-scoped authenticated API and supports refresh', async () => {
  const calls = []
  const history = createRaffleHistory({ request: async (path, options) => { calls.push([path, options]); return [entry] } })
  await history.load(customer.customer_id)
  assert.deepEqual(history.getSnapshot().entries, [entry])
  assert.deepEqual(calls[0], ['/customers/fictional-customer/raffle-entries', { cache: 'no-store' }])
  await history.load(customer.customer_id); assert.equal(calls.length, 2)
  let fetches = 0
  const request = createAuthenticatedClient({ base: 'http://api.test', getToken: async () => { throw Error('No authenticated session') },
    onExpired: () => {}, fetchRequest: async () => { fetches++; return new Response('[]') } })
  const anonymous = createRaffleHistory({ request })
  await anonymous.load(customer.customer_id)
  assert.equal(fetches, 0)
  assert.ok(anonymous.getSnapshot().error)
  assert.equal(anonymous.getSnapshot().entries, null)
})

test('failed history handles retry and unmount ignores late replies', async () => {
  let succeed = false
  const history = createRaffleHistory({ request: async () => { if (!succeed) throw Error('Failed to fetch'); return [] } })
  await history.load(customer.customer_id)
  assert.match(history.getSnapshot().error, /Cannot load Daily Raffle history/)
  succeed = true; await history.load(customer.customer_id)
  assert.deepEqual(history.getSnapshot().entries, []); assert.equal(history.getSnapshot().error, '')
  let release
  const late = createRaffleHistory({ request: () => new Promise(resolve => { release = resolve }) })
  const pending = late.load(customer.customer_id); late.cancel(); release([entry]); await pending
  assert.equal(late.getSnapshot().entries, null)
})

test('actual history view renders date, visit number, Dublin time, empty/error/loading states and ten recent entries', () => {
  const render = state => renderToStaticMarkup(createElement(CustomerRaffleView, { state, onRefresh: () => {} }))
  const html = render({ entries: [entry], busy: false, error: '' })
  assert.match(html, /Daily Raffle/); assert.match(html, /2026-10-07/)
  assert.match(html, /Visit 1/); assert.match(html, /Europe\/Dublin/)
  assert.doesNotMatch(html, /random-visit-id|fictional-customer|PHONE#|RAFFLE#/)
  assert.match(render({ entries: [], busy: false, error: '' }), /No Daily Raffle entries yet/)
  assert.match(render({ entries: null, busy: true, error: '' }), /role="status"/)
  assert.match(render({ entries: null, busy: false, error: 'Please try again.' }), /role="alert"/)
  const many = Array.from({ length: 12 }, (_, index) => ({ ...entry, raffle_entry_id: `fixture-${index}`, visit_number: index + 1 }))
  assert.equal((render({ entries: many, busy: false, error: '' }).match(/<li/g) || []).length, 10)
})

test('profile and actual scanner render paths use raffle history and separate success messages', () => {
  const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  assert.match(source('../src/components/CustomerProfile.jsx'), /<CustomerRaffle/)
  assert.match(source('../src/components/CustomerRaffle.jsx'), /createRaffleHistory\(\{ request: apiRequest \}\)/)
  assert.match(source('../src/components/VisitScanner.jsx'), /visitSuccessMessages\(result\).map/)
  assert.match(source('../src/components/VisitScanner.jsx'), /✓ \{message\}/)
  assert.doesNotMatch(source('../src/components/CustomerRaffle.jsx'), /window.print|raffle.draw/)
})
