import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { createSMSFlow } from '../src/smsFlow.js'
import SMSAudienceCards from '../src/components/SMSAudienceCards.js'
import SMSCustomerResults from '../src/components/SMSCustomerResults.js'
const eligible = { customer_id: 'a', name: 'Sarah Fictional', masked_phone: '+•••••••4567', sms_eligible: true, ineligible_reason: null }
const optedOut = { ...eligible, customer_id: 'b', name: 'Jane Fictional', sms_eligible: false, ineligible_reason: 'Customer has opted out of SMS.' }
const response = { results: [eligible, optedOut], total_matches: 2 }

test('partial names and Irish phones query the scoped SMS endpoint; selection writes nothing', async () => {
  for (const role of ['OWNER', 'MANAGER']) {
    const calls = []
    const flow = createSMSFlow({ role, request: async (...args) => { calls.push(args); return response } })
    for (const query of ['sar', 'Fictional', 'Sarah Fic', '0831234567', '831234567', '+353831234567', '353831234567']) {
      await flow.searchCustomers(query)
      assert.equal(calls.at(-1)[0], `/sms/customers?q=${encodeURIComponent(query)}`)
      assert.deepEqual(calls.at(-1)[1], { cache: 'no-store' })
      assert.equal(flow.selectCustomer('a'), true)
      assert.equal(flow.getSnapshot().selectedCustomer.name, 'Sarah Fictional')
      assert.equal(flow.selectCustomer('b'), false)
      assert.equal(flow.getSnapshot().selectedCustomer.customer_id, 'a')
    }
    assert.ok(calls.every(([, options]) => !options.method))
    assert.equal(flow.getSnapshot().preview, null)
  }
})
test('empty input, loading, no results, error and retry have independent states', async () => {
  let count = 0
  const flow = createSMSFlow({ role: 'OWNER', request: async () => { count++; if (count === 1) throw Error('Failed to fetch'); return { results: [], total_matches: 0 } } })
  await flow.searchCustomers(' '); assert.equal(count, 0)
  flow.prepareSearch('Sarah'); assert.equal(flow.getSnapshot().searchLoading, true)
  await flow.searchCustomers('Sarah'); assert.match(flow.getSnapshot().searchError, /Unable to search/)
  await flow.searchCustomers('Sarah'); assert.equal(flow.getSnapshot().searchError, ''); assert.equal(flow.getSnapshot().searchTotal, 0)
  const render = props => renderToStaticMarkup(h(SMSCustomerResults, { query: '', results: [], loading: false, error: '', total: 0, ...props }))
  assert.match(render({}), /Type a name/)
  assert.match(render({ query: 'S', loading: true }), /Searching customers/)
  assert.match(render({ query: 'S' }), /No matching customers/)
  assert.match(render({ query: 'S', error: 'Unavailable' }), /Retry customer search/)
})
test('settings/history failure does not discard or block customer search', async () => {
  const flow = createSMSFlow({ role: 'OWNER', request: async path => { if (path.startsWith('/sms/customers?')) return response; throw Error('History unavailable') } })
  assert.equal(await flow.load(), false)
  assert.equal(await flow.searchCustomers('Sarah'), true)
  assert.equal(flow.getSnapshot().searchResults.length, 2)
  assert.equal(flow.selectCustomer('a'), true)
})
test('stale or unmounted requests never replace new query results or identity', async () => {
  const pending = []
  const flow = createSMSFlow({ role: 'OWNER', request: () => new Promise(resolve => pending.push(resolve)) })
  const old = flow.searchCustomers('Old'); const latest = flow.searchCustomers('Sarah')
  pending[1](response); await latest
  pending[0]({ results: [], total_matches: 0 }); await old
  assert.equal(flow.getSnapshot().searchResults[0].name, 'Sarah Fictional')
  const late = flow.searchCustomers('Other'); flow.cancel(); pending[2](response); await late
  assert.equal(flow.getSnapshot().searchResults.length, 0)
  assert.equal(flow.getSnapshot().selectedCustomer, null)
})
test('selection persists across queries; audience/clear removes selection and preview', async () => {
  let result = response
  const flow = createSMSFlow({ role: 'MANAGER', request: async () => result })
  await flow.searchCustomers('Sarah'); flow.selectCustomer('a')
  result = { results: [], total_matches: 0 }; await flow.searchCustomers('Nobody')
  assert.equal(flow.getSnapshot().selectedCustomer.customer_id, 'a')
  flow.clearSelection()
  assert.equal(flow.getSnapshot().selectedCustomer, null); assert.equal(flow.getSnapshot().searchQuery, '')
  assert.equal(await flow.preview({ audience: 'individual', customer_id: 'a', message: 'Hi' }), false)
})
test('updated ineligibility and explicit opt-out invalidate selected recipient', async () => {
  let result = response
  const flow = createSMSFlow({ role: 'OWNER', request: async () => result })
  await flow.searchCustomers('Sarah'); flow.selectCustomer('a')
  result = { results: [{ ...optedOut, customer_id: 'a' }], total_matches: 1 }
  await flow.searchCustomers('Sarah')
  assert.equal(flow.getSnapshot().selectedCustomer.sms_eligible, false)
  assert.equal(await flow.preview({ audience: 'individual', customer_id: 'a', message: 'Hi' }), false)
  assert.equal(flow.getSnapshot().preview, null)
})
test('Staff cannot search or select and no caller business is added', async () => {
  let count = 0
  const flow = createSMSFlow({ role: 'STAFF', request: async () => { count++ } })
  flow.prepareSearch('Sarah'); await flow.searchCustomers('Sarah'); assert.equal(flow.selectCustomer('a'), false)
  assert.equal(count, 0)
})
test('visible results mask phones, explain ineligibility and escape customer text', () => {
  const html = renderToStaticMarkup(h(SMSCustomerResults, { query: 'Sarah', results: [eligible, optedOut], total: 2, selected: eligible }))
  assert.match(html, /Sarah Fictional/); assert.match(html, /Eligible for SMS/); assert.match(html, /has opted out/)
  assert.match(html, /aria-pressed="true"/); assert.match(html, /disabled=""/)
  assert.doesNotMatch(html, /\+353831234567/)
  const escaped = renderToStaticMarkup(h(SMSCustomerResults, { query: 'x', results: [{ ...eligible, name: '<script>bad</script>' }], total: 1 }))
  assert.doesNotMatch(escaped, /<script>/)
})
test('cards retain native radio semantics and responsive focus/theme styling', () => {
  const html = renderToStaticMarkup(h(SMSAudienceCards, { value: 'individual', onChange() {} }))
  assert.equal((html.match(/type="radio"/g) || []).length, 2)
  assert.equal((html.match(/name="sms-audience"/g) || []).length, 2)
  assert.match(html, /Individual Customer/); assert.match(html, /All Eligible Customers/)
  assert.match(html, /aria-describedby="sms-audience-individual-description"/)
  assert.match(html, /sms-audience-card is-selected/)
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
  assert.match(css, /\.sms-audience-card:focus-within/)
  assert.match(css, /input\[type="radio"\][^}]*width: 18px/)
  assert.match(css, /\.sms-audience-card.is-selected[^}]*var\(--theme-primary\)/)
  assert.match(css, /@media \(max-width: 600px\)[\s\S]*\.sms-audience-cards \{ grid-template-columns: 1fr/)
  const source = readFileSync(new URL('../src/components/SMSMessaging.jsx', import.meta.url), 'utf8')
  assert.match(source, /flow.clearSelection\(\); edit\(\{ audience, customer_id: '' \}\)/)
  assert.match(source, /setTimeout\(\(\) => flow.searchCustomers\(search\), 250\)/)
})

test('a pending metadata request does not disable or hold up customer search', async () => {
  const pending = []
  const flow = createSMSFlow({ role: 'OWNER', request: path => path.startsWith('/sms/customers?') ? Promise.resolve(response) : new Promise(resolve => pending.push(resolve)) })
  const loading = flow.load()
  assert.equal(flow.getSnapshot().metadataLoading, true)
  assert.equal(flow.getSnapshot().busy, false)
  await flow.searchCustomers('Sarah')
  assert.equal(flow.selectCustomer('a'), true)
  pending[0]({}); pending[1]([]); await loading
  assert.equal(flow.getSnapshot().selectedCustomer.customer_id, 'a')
})
