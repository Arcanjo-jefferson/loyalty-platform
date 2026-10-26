import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import SMSHistory from '../src/components/SMSHistory.js'
import { smsStatusLabel } from '../src/smsStatus.js'

test('delivery labels distinguish accepted, sent, delivered, failed, unknown and simulation', () => {
  assert.equal(smsStatusLabel('QUEUED'), 'Queued')
  assert.match(smsStatusLabel('ACCEPTED'), /Queued.*delivery not confirmed/)
  assert.match(smsStatusLabel('SENT'), /^Sent.*delivery not confirmed/)
  assert.equal(smsStatusLabel('DELIVERED'), 'Delivered')
  for (const state of ['FAILED', 'UNDELIVERED']) assert.match(smsStatusLabel(state), /^Failed/)
  assert.match(smsStatusLabel('UNKNOWN'), /^Delivery unknown/)
  assert.equal(smsStatusLabel('SIMULATED'), 'Simulation complete — no real SMS sent')
})

test('history displays per-recipient delivery status with masked phone and unchanged simulation', () => {
  const campaign = { campaign_id: 'fixture', created_at: '2026-10-26T12:00:00Z', recipient_count: 3,
    recipients: ['SIMULATED', 'DELIVERED', 'UNKNOWN'].map((status, i) => ({ id: String(i), name: 'Fictional customer',
      phone: '+353831234567', body: 'Fixture message', updated_at: '2026-10-26T12:00:00Z', status })) }
  const html = renderToStaticMarkup(createElement(SMSHistory, { history: [campaign] }))
  assert.match(html, /Simulation complete — no real SMS sent/)
  assert.match(html, /Delivered/); assert.match(html, /Delivery unknown/)
  assert.doesNotMatch(html, /\+353831234567|provider_message_id/)
})
