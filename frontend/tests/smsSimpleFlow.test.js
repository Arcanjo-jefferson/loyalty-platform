import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { createSMSFlow, composeSMSPreview } from '../src/smsFlow.js'
import { campaignOutcome, smsStatusLabel } from '../src/smsStatus.js'
import SMSConfirmation from '../src/components/SMSConfirmation.js'
import SMSHistory from '../src/components/SMSHistory.js'
const draft = { campaign_id: 'reviewed-id', status: 'DRAFT', recipient_count: 3, estimated_cost_micros: 300000,
  sender: 'Trumps', recipients: [{ id: 'a', name: 'Sarah', phone: '+353831234567', body: 'Hi Sarah', status: 'DRAFT' }] }
const values = { audience: 'all', message: 'Hi {first_name}' }
const queued = { ...draft, status: 'QUEUED', recipients: draft.recipients.map(r => ({ ...r, status: 'QUEUED' })) }
const done = { ...queued, status: 'FINISHED', recipients: draft.recipients.map(r => ({ ...r, status: 'SIMULATED' })) }
const elements = node => !node || typeof node !== 'object' ? [] : [node, ...[node.props?.children].flat(Infinity).flatMap(elements)]

test('Send only opens confirmation; final explicit Yes queues the reviewed campaign once', async () => {
  const calls = []
  const flow = createSMSFlow({ role: 'MANAGER', request: async (path, options) => { calls.push([path, options]); return path.endsWith('/confirm') ? queued : draft } })
  assert.equal(flow.getSnapshot().stage, 'compose')
  await flow.review(values)
  assert.equal(flow.getSnapshot().stage, 'confirm')
  assert.equal(calls.length, 1); assert.equal(calls[0][0], '/sms/preview')
  assert.equal(await flow.confirm(false), false); assert.equal(calls.length, 1)
  await flow.confirm(true)
  assert.equal(calls[1][0], '/sms/campaigns/reviewed-id/confirm')
  assert.deepEqual(JSON.parse(calls[1][1].body), { confirmed: true })
  assert.equal(flow.getSnapshot().stage, 'result')
  assert.match(flow.getSnapshot().notice, /queued for simulation/)
  assert.doesNotMatch(flow.getSnapshot().notice, /were delivered/)
  assert.equal(await flow.confirm(true), false)
})
test('Go back preserves composition and idempotency; editing invalidates the review', async () => {
  const calls = []; const flow = createSMSFlow({ role: 'OWNER', request: async path => { calls.push(path); return draft } })
  await flow.review(values); flow.goBack(); assert.equal(flow.getSnapshot().stage, 'compose')
  await flow.review(values); assert.equal(calls.length, 1, 'Re-review of unchanged message uses same campaign')
  flow.goBack(); flow.invalidate(); await flow.review({ ...values, message: 'Changed' })
  assert.equal(calls.length, 2)
  flow.reset(); assert.equal(flow.getSnapshot().stage, 'compose'); assert.equal(flow.getSnapshot().preview, null)
  assert.equal(await flow.confirm(true), false)
})
test('Cancel during review ignores a late response and does not queue anything', async () => {
  let finish
  const flow = createSMSFlow({ role: 'OWNER', request: () => new Promise(resolve => { finish = resolve }) })
  const reviewing = flow.review(values); flow.reset(); finish(draft); await reviewing
  assert.equal(flow.getSnapshot().stage, 'compose'); assert.equal(flow.getSnapshot().preview, null)
})
test('failed confirmation stays reviewable; uncertain network failure retries only the same id', async () => {
  const calls = []; let failure = true
  const flow = createSMSFlow({ role: 'OWNER', request: async path => {
    calls.push(path)
    if (!path.endsWith('/confirm')) return draft
    if (failure) throw Error('Failed to fetch')
    return queued
  } })
  await flow.review(values); assert.equal(await flow.confirm(true), false)
  assert.equal(flow.getSnapshot().stage, 'confirm'); assert.equal(flow.getSnapshot().preview.campaign_id, 'reviewed-id')
  assert.equal(flow.getSnapshot().notice, ''); assert.match(flow.getSnapshot().error, /check message history/)
  failure = false; await flow.confirm(true)
  assert.deepEqual(calls.slice(1), ['/sms/campaigns/reviewed-id/confirm', '/sms/campaigns/reviewed-id/confirm'])
})
test('server budget or eligibility rejection returns to compose without success', async () => {
  const flow = createSMSFlow({ role: 'OWNER', request: async path => {
    if (!path.endsWith('/confirm')) return draft
    throw Object.assign(Error('Monthly spending limit exceeded.'), { status: 409 })
  } })
  await flow.review(values); await flow.confirm(true)
  assert.equal(flow.getSnapshot().stage, 'compose'); assert.equal(flow.getSnapshot().preview, null)
  assert.match(flow.getSnapshot().error, /spending limit/); assert.equal(flow.getSnapshot().notice, '')
})
test('result polling is read-only and distinguishes simulation from delivery', async () => {
  const calls = []
  const flow = createSMSFlow({ role: 'OWNER', request: async (path, options) => {
    calls.push([path, options]); return path === '/sms/preview' ? draft : path.endsWith('/confirm') ? queued : done
  } })
  await flow.review(values); await flow.confirm(true); await flow.refreshResult()
  assert.equal(calls.at(-1)[0], '/sms/campaigns/reviewed-id')
  assert.equal(calls.at(-1)[1].method, undefined)
  assert.match(flow.getSnapshot().notice, /Simulation completed successfully/)
  flow.reset(); assert.equal(flow.getSnapshot().result, null)
  assert.equal(smsStatusLabel('QUEUED'), 'Queued')
  assert.match(smsStatusLabel('SIMULATED'), /no real SMS/)
  assert.equal(smsStatusLabel('DELIVERED'), 'Delivered')
  assert.match(campaignOutcome({ recipients: [{ status: 'UNKNOWN' }] }).message, /will not be sent again automatically/)
})
test('confirmation has exactly two buttons and authoritative count/cost', () => {
  let confirmed = 0; let back = 0
  const tree = SMSConfirmation({ preview: draft, busy: false, onConfirm: () => confirmed++, onBack: () => back++ })
  const buttons = elements(tree).filter(e => e.type === 'button')
  assert.equal(buttons.length, 2)
  assert.deepEqual(buttons.map(b => b.props.children), ['Yes, confirm send', 'Go back'])
  buttons[0].props.onClick(); buttons[1].props.onClick(); assert.equal(confirmed, 1); assert.equal(back, 1)
  const html = renderToStaticMarkup(h(SMSConfirmation, { preview: draft }))
  assert.match(html, /3 eligible customers/); assert.match(html, /€0.30/); assert.match(html, /simulation/)
  assert.doesNotMatch(html, /GSM-7|SMS segment|type="checkbox"/)
})
test('local composition preview is illustrative for bulk and never alters the submitted template', () => {
  const original = structuredClone(values)
  assert.equal(composeSMSPreview({ ...values, audience: 'individual' }, null), null)
  const selected = { customer_id: 'a', name: 'Mary Jane Fictional', first_name: 'Mary Jane', masked_phone: '••4567' }
  const body = composeSMSPreview({ ...values, audience: 'individual' }, selected).recipients[0].body
  assert.equal(body, 'Hi Mary Jane')
  assert.equal(composeSMSPreview(values).recipients[0].body, 'Hi Sarah')
  assert.deepEqual(values, original)
})
test('history shows readable statuses and masked phones without technical audit details', () => {
  const html = renderToStaticMarkup(h(SMSHistory, { history: [{ ...done, created_at: '2026-10-19T12:00:00Z' }] }))
  assert.match(html, /Simulation complete/); assert.doesNotMatch(html, /SIMULATED|FINISHED|consent_decision|\+353831234567/)
  const source = readFileSync(new URL('../src/components/SMSMessaging.jsx', import.meta.url), 'utf8')
  for (const text of ['Send message', 'Cancel', 'Start a new message', 'Message history']) assert.ok(source.includes(text))
  assert.doesNotMatch(source, /Process simulated queue|Refresh history and budget|flow.simulate|SMS encoding|segment_price/)
})

test('an empty audience stays in compose and the next Send checks fresh eligibility', async () => {
  let count = 0
  const flow = createSMSFlow({ role: 'OWNER', request: async () => ++count === 1 ? { ...draft, recipient_count: 0, recipients: [] } : draft })
  assert.equal(await flow.review(values), false)
  assert.equal(flow.getSnapshot().stage, 'compose'); assert.equal(flow.getSnapshot().preview, null)
  assert.equal(await flow.review(values), true)
  assert.equal(flow.getSnapshot().stage, 'confirm'); assert.equal(count, 2)
})
