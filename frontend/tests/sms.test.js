import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { canUseSMS, createSMSFlow, exampleSMS, smsMoney } from '../src/smsFlow.js'
import SMSPreview from '../src/components/SMSPreview.js'
import SMSHistory from '../src/components/SMSHistory.js'

const preview = { campaign_id: 'canonical-id', message: 'Hi {first_name}', status: 'DRAFT', recipient_count: 1, excluded_count: 2,
  total_segments: 1, estimated_cost_micros: 100000, sender: 'Simulation sender', recipients: [{ id: 'customer-a', name: '<script>Sarah</script>', phone: '+353831234567', body: 'Hi Sarah', characters: 8, encoding: 'GSM-7', segments: 1 }] }
const settings = { provider: 'simulation', reserved_micros: 0 }
const requestFor = calls => async (path, options = {}) => {
  calls.push([path, options])
  if (path.startsWith('/sms/customers?q=')) return { results: [{ customer_id: 'customer-a', name: 'Sarah Fictional', masked_phone: '+•••••••4567', sms_eligible: true, ineligible_reason: null }], total_matches: 1 }
  if (path === '/sms/settings') return settings
  if (path === '/sms/history') return []
  if (path === '/sms/preview') return structuredClone(preview)
  if (path.endsWith('/confirm')) return { ...preview, status: 'QUEUED', recipients: preview.recipients.map(r => ({ ...r, status: 'QUEUED' })) }
  return { provider: 'simulation', processed: 1 }
}

test('Owner and Manager load scoped data, compose individual message, explicitly confirm canonical preview', async () => {
  for (const role of ['OWNER', 'MANAGER']) {
    const calls = []; const flow = createSMSFlow({ role, request: requestFor(calls) })
    await flow.load()
    await flow.searchCustomers('Sarah')
    assert.equal(flow.selectCustomer('customer-a'), true)
    await flow.preview({ audience: 'individual', customer_id: 'customer-a', message: 'Hi {first_name}' })
    assert.equal(await flow.confirm(false), false)
    assert.equal(calls.filter(([path]) => path.endsWith('/confirm')).length, 0)
    assert.equal(await flow.confirm(true), true)
    const confirmation = calls.find(([path]) => path.endsWith('/confirm'))
    assert.equal(confirmation[0], '/sms/campaigns/canonical-id/confirm')
    assert.deepEqual(JSON.parse(confirmation[1].body), { confirmed: true })
    assert.equal(flow.getSnapshot().history[0].status, 'QUEUED')
    assert.match(flow.getSnapshot().notice, /simulation/)
    assert.equal(await flow.confirm(true), false)
  }
})
test('Staff and anonymous roles cannot make any SMS or customer-list request', async () => {
  for (const role of ['STAFF', undefined]) {
    let calls = 0; const flow = createSMSFlow({ role, request: async () => { calls++ } })
    await flow.load(); await flow.preview({}); await flow.confirm(true); await flow.simulate(); await flow.suppress('a', true)
    assert.equal(calls, 0); assert.match(flow.getSnapshot().error, /Only Owner and Manager/)
    assert.equal(canUseSMS(role), false)
  }
})
test('bulk submit sends editable template without caller identity or estimates', async () => {
  const calls = []; const flow = createSMSFlow({ role: 'MANAGER', request: requestFor(calls) })
  await flow.preview({ audience: 'all', customer_id: 'ignored', message: exampleSMS, business_id: 'other', estimated_cost_micros: 0 })
  assert.deepEqual(JSON.parse(calls[0][1].body), { audience: 'all', message: exampleSMS })
  assert.equal(flow.getSnapshot().preview.recipient_count, 1)
  assert.equal(flow.getSnapshot().preview.total_segments, 1)
})
test('editing invalidates preview and zero recipients cannot be confirmed', async () => {
  const calls = []; const flow = createSMSFlow({ role: 'OWNER', request: requestFor(calls) })
  await flow.preview({ audience: 'all', message: 'Hi' }); flow.invalidate()
  assert.equal(await flow.confirm(true), false)
  const zero = createSMSFlow({ role: 'OWNER', request: async () => ({ ...preview, recipient_count: 0 }) })
  await zero.preview({ audience: 'all', message: 'Hi' })
  assert.equal(await zero.confirm(true), false)
})
test('queue failure preserves preview for idempotent retry without false success', async () => {
  const calls = []; const normal = requestFor(calls); let fail = true
  const flow = createSMSFlow({ role: 'OWNER', request: (path, options) => {
    if (path.endsWith('/confirm') && fail) throw Error('Monthly SMS spending limit exceeded.')
    return normal(path, options)
  } })
  await flow.preview({ audience: 'all', message: 'Hi' })
  assert.equal(await flow.confirm(true), false)
  assert.equal(flow.getSnapshot().preview.campaign_id, 'canonical-id')
  assert.equal(flow.getSnapshot().notice, ''); assert.match(flow.getSnapshot().error, /spending limit/)
  fail = false; assert.equal(await flow.confirm(true), true)
})
test('simulation action refreshes history and never calls a Twilio URL', async () => {
  const calls = []; const flow = createSMSFlow({ role: 'OWNER', request: requestFor(calls) })
  await flow.simulate()
  assert.equal(calls[0][0], '/sms/simulate'); assert.deepEqual(JSON.parse(calls[0][1].body), {})
  assert.match(flow.getSnapshot().notice, /no real SMS/)
  assert.equal(calls.some(([path]) => path.includes('twilio')), false)
})
test('confirmed opt-out clears stale preview and cancellation prevents late profile data', async () => {
  const calls = []; const flow = createSMSFlow({ role: 'MANAGER', request: requestFor(calls) })
  await flow.preview({ audience: 'all', message: 'Hi' })
  assert.equal(await flow.suppress('customer-a', false), false)
  await flow.suppress('customer-a', true)
  assert.equal(flow.getSnapshot().preview, null)
  assert.deepEqual(JSON.parse(calls.at(-1)[1].body), { confirmed: true })
  let resolve
  const late = createSMSFlow({ role: 'OWNER', request: () => new Promise(done => { resolve = done }) })
  const pending = late.preview({ audience: 'all', message: 'Hi' }); late.cancel(); resolve(preview); await pending
  assert.equal(late.getSnapshot().preview, null)
})
test('preview/history show safe escaped content, encoding, count, cost, simulation and times', () => {
  const html = renderToStaticMarkup(createElement(SMSPreview, { preview }))
  assert.match(html, /Message preview/); assert.doesNotMatch(html, /GSM-7|SMS segment/)
  assert.match(html, /&lt;script&gt;/); assert.doesNotMatch(html, /<script>/)
  assert.equal(smsMoney(100000), '€0.10')
  const history = renderToStaticMarkup(createElement(SMSHistory, { history: [{ ...preview, created_at: '2026-10-16T12:00:00Z', recipients: preview.recipients.map(r => ({ ...r, updated_at: '2026-10-16T12:00:00Z', status: 'SIMULATED' })) }] }))
  assert.match(history, /Simulation complete/); assert.match(history, /no real SMS sent/); assert.match(history, /Europe\/Dublin/)
})
test('actual app route and form use role guard, editable message and explicit review controls', () => {
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
  const component = readFileSync(new URL('../src/components/SMSMessaging.jsx', import.meta.url), 'utf8')
  assert.match(app, /path === '\/sms'/); assert.match(app, /SMSMessaging/)
  assert.match(app, /\['OWNER', 'MANAGER'\].includes\(user.role\)/)
  assert.match(component, /if \(!canUseSMS\(user.role\)\)/)
  assert.match(component, /key=\{`\$\{user.business_id\}:\$\{user.subject\}`\}/)
  assert.match(component, /flow.searchCustomers\(search\)/)
  assert.match(component, /textarea rows="7"/); assert.match(component, /flow.invalidate\(\)/)
  assert.match(component, /onConfirm=\{\(\) => flow.confirm\(true\)\}/); assert.doesNotMatch(component, /window.alert|dangerouslySetInnerHTML/)
})
