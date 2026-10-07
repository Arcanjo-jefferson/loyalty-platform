import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { createVisitFlow } from '../src/visitFlow.js'
import ManualCustomerResults from '../src/components/ManualCustomerResults.js'
import { createAuthenticatedClient } from '../src/httpClient.js'

const customer = { customer_id: 'fixture-one', first_name: 'Fictional', last_name: 'Customer', phone: '+353831234567', status: 'active' }
const other = { customer_id: 'fixture-two', first_name: 'Fictional', last_name: 'Other', phone: '+353871234567', status: 'active' }
const details = person => ({ customer: person, total_visits: 4, progress: 4, visits_until_reward: 1, visits: [] })
const raffle = { raffle_entry_id: 'fixture-entry', visit_id: 'fixture-visit' }

test('Loyalty Visits search reuses first/last/full names and all equivalent Irish phone representations', async () => {
  const calls = []
  const flow = createVisitFlow({ request: async (path, options) => { calls.push([path, options]); return [customer, other] } })
  for (const query of ['Customer', 'Fictional Customer', 'fictional   customer', '0831234567', '831234567', '+353831234567', '353831234567']) {
    await flow.search(query)
    assert.deepEqual(flow.getSnapshot().matches, [customer], query)
    assert.equal(flow.getSnapshot().result, null)
  }
  await flow.search('Fictional'); assert.deepEqual(flow.getSnapshot().matches, [customer, other])
  assert.ok(calls.every(([path, options]) => path === '/customers' && !options.method && !options.body))
  await flow.search('no match'); assert.deepEqual(flow.getSnapshot().matches, [])
})

test('multiple matches can each be selected with read-only fresh progress and no visit/raffle/voucher creation', async () => {
  const calls = []
  const flow = createVisitFlow({ request: async (path, options) => {
    calls.push([path, options])
    if (path === '/customers') return [customer, other]
    return details(path.includes(other.customer_id) ? other : customer)
  } })
  await flow.search('Fictional')
  for (const person of [other, customer]) {
    await flow.select(person.customer_id)
    assert.equal(flow.getSnapshot().stage, 'ready')
    assert.equal(flow.getSnapshot().result.customer.customer_id, person.customer_id)
    assert.equal(flow.getSnapshot().result.progress, 4)
    assert.equal(flow.getSnapshot().notice, '')
    assert.equal(flow.getSnapshot().result.raffle_entry, undefined)
  }
  assert.ok(calls.every(([, options]) => !options.method && !options.body))
  assert.deepEqual(calls.map(([path]) => path), ['/customers', '/customers/fixture-two/visits', '/customers/fixture-one/visits'])
  flow.clear(); assert.equal(flow.getSnapshot().result, null); assert.equal(flow.getSnapshot().matches, null)
  await flow.select(customer.customer_id); await flow.confirm(); assert.equal(calls.length, 3)
  await flow.search('Customer'); assert.deepEqual(flow.getSnapshot().matches, [customer])
})

test('QR and manual selection call the identical confirmation endpoint/body and show the same 5C rewards', async () => {
  for (const method of ['manual', 'qr']) {
    const calls = []
    const flow = createVisitFlow({ request: async (path, options) => {
      calls.push([path, options])
      if (path === '/customers') return [customer]
      if (options.method === 'POST' && path.endsWith('/visits')) return { ...details(customer), total_visits: 5, progress: 0, raffle_entry: raffle, vouchers: [{ type: 'LOYALTY_10' }, { type: 'BIRTHDAY_20' }] }
      return details(customer)
    } })
    if (method === 'manual') { await flow.search('Customer'); await flow.select(customer.customer_id) }
    else await flow.lookup('fixture-qr-token-123')
    assert.equal(flow.getSnapshot().stage, 'ready'); assert.equal(flow.getSnapshot().notice, '')
    await flow.confirm()
    const writes = calls.filter(([path, options]) => path.endsWith('/visits') && options.method === 'POST')
    assert.deepEqual(writes, [['/customers/fixture-one/visits', { method: 'POST', body: '{}', cache: 'no-store' }]])
    assert.match(flow.getSnapshot().notice, /Visit recorded successfully.*Daily Raffle entry created.*€10 Loyalty Voucher earned.*€20 Birthday Voucher issued/)
    await flow.confirm(); assert.equal(calls.length, method === 'manual' ? 3 : 2)
  }
})

test('manual duplicate confirmation preserves progress and never shows raffle or reward success', async () => {
  const flow = createVisitFlow({ request: async (path, options) => {
    if (path === '/customers') return [customer]
    if (options.method === 'POST') throw Error('A loyalty visit has already been recorded for this customer today.')
    return details(customer)
  } })
  await flow.search('0831234567'); await flow.select(customer.customer_id); await flow.confirm()
  assert.equal(flow.getSnapshot().stage, 'ready'); assert.equal(flow.getSnapshot().result.progress, 4)
  assert.match(flow.getSnapshot().error, /already been recorded/); assert.equal(flow.getSnapshot().notice, '')
})

test('inactive search results and freshly deactivated customers cannot become confirmable', async () => {
  let reads = 0
  const inactive = { ...customer, status: 'inactive' }
  const flow = createVisitFlow({ request: async path => { reads++; return path === '/customers' ? [inactive] : details(inactive) } })
  await flow.search('Customer'); await flow.select(customer.customer_id); await flow.confirm()
  assert.equal(reads, 1); assert.equal(flow.getSnapshot().result, null)
  assert.match(flow.getSnapshot().error, /Inactive customers/)
  const stale = createVisitFlow({ request: async path => path === '/customers' ? [customer] : details(inactive) })
  await stale.search('Customer'); await stale.select(customer.customer_id)
  assert.equal(stale.getSnapshot().stage, 'search-results'); assert.equal(stale.getSnapshot().result, null)
  assert.match(stale.getSnapshot().error, /Inactive customers/)
})

test('manual lookup handles unavailable customers, search failures and cancellation without stale confirmation', async () => {
  const unavailable = createVisitFlow({ request: async path => {
    if (path === '/customers') return [customer]
    throw Object.assign(Error('not found'), { status: 404 })
  } })
  await unavailable.search('Customer'); await unavailable.select(customer.customer_id)
  assert.match(unavailable.getSnapshot().error, /Customer is unavailable/)
  assert.equal(unavailable.getSnapshot().result, null)
  const failed = createVisitFlow({ request: async () => { throw Error('Failed to fetch') } })
  await failed.search('Customer'); assert.match(failed.getSnapshot().error, /Cannot search/)
  let release
  const flow = createVisitFlow({ request: async path => path === '/customers' ? [customer] : new Promise(resolve => { release = resolve }) })
  await flow.search('Customer'); const pending = flow.select(customer.customer_id)
  await flow.confirm(); flow.cancel(); release(details(customer)); await pending
  assert.equal(flow.getSnapshot().result, null); assert.equal(flow.getSnapshot().notice, '')
})

test('manual customer directory uses existing authenticated transport and sends no tenant or recorder', async () => {
  const calls = []
  const request = createAuthenticatedClient({ base: 'http://api.test', getToken: async () => 'fixture-id-token', onExpired: () => {},
    fetchRequest: async (url, options) => { calls.push([url, options]); return new Response(JSON.stringify(url.endsWith('/customers') ? [customer] : details(customer)), { status: 200 }) } })
  const flow = createVisitFlow({ request }); await flow.search('Customer'); await flow.select(customer.customer_id)
  assert.equal(calls.length, 2)
  for (const [url, options] of calls) {
    assert.equal(options.headers.Authorization, 'Bearer fixture-id-token')
    assert.doesNotMatch(url, /business_id|recorded_by|tenant/)
    assert.equal(options.body, undefined)
  }
  let fetches = 0
  const anonymous = createVisitFlow({ request: createAuthenticatedClient({ base: 'http://api.test', getToken: async () => { throw Error('not signed in') }, onExpired: () => {}, fetchRequest: async () => { fetches++ } }) })
  await anonymous.search('Customer'); assert.equal(fetches, 0); assert.equal(anonymous.getSnapshot().result, null)
})

test('actual results view is compact, selectable, accessible and hides unnecessary private customer fields', () => {
  const html = renderToStaticMarkup(createElement(ManualCustomerResults, { matches: [{ ...customer, date_of_birth: '1990-01-01', qr_token: 'private-qr' }, { ...other, status: 'inactive' }], busy: false, onSelect: () => {} }))
  assert.match(html, /Fictional Customer/); assert.match(html, /\+353831234567/)
  assert.equal((html.match(/Select customer/g) || []).length, 2)
  assert.match(html, /Inactive/); assert.match(html, /disabled/)
  assert.doesNotMatch(html, /1990-01-01|private-qr|fixture-one|PHONE_LOCK|QR_LOCK|RAFFLE_DATE/)
  const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  const scanner = source('../src/components/VisitScanner.jsx')
  assert.match(scanner, /Scan customer QR/); assert.match(scanner, /Find customer/)
  assert.match(scanner, /flow.search\(query\)/); assert.match(scanner, /flow.select\(customerId\)/)
  assert.match(scanner, /CustomerPhoto/); assert.match(scanner, /result.customer.phone/)
  assert.match(scanner, /flow.confirm\(\)/); assert.match(scanner, /Clear \/ change customer/)
})
