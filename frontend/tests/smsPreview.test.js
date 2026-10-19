import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement as h } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import SMSPreview, { SMSPreviewLayout, previewRecipient, maskedPreviewPhone } from '../src/components/SMSPreview.js'
import { createSMSFlow } from '../src/smsFlow.js'
const preview = {
  campaign_id: 'preview-one', recipient_count: 2, total_segments: 3, estimated_cost_micros: 300000,
  excluded_count: 4, sender: 'TRUMPS PLAZA', status: 'DRAFT', recipients: [
    { id: 'sarah', name: 'Sarah Fictional', phone: '+353831234567', body: 'TRUMPS PLAZA\n\nHi Sarah!\n  Keep these spaces.\n\nReply STOP to opt out.', encoding: 'GSM-7', characters: 73, segments: 1 },
    { id: 'jane', name: 'Jane Fictional', phone: '+353871234568', body: 'Hi Jane!\n\nA different personalised message 😀', encoding: 'UCS-2', characters: 44, segments: 2 },
  ],
}
const render = (value = preview, props = {}) => renderToStaticMarkup(h(SMSPreviewLayout, { preview: value, ...props }))
const elements = node => !node || typeof node !== 'object' ? [] : [node, ...[node.props?.children].flat(Infinity).flatMap(elements)]

test('simple preview hides encoding, counts, cost and queue details', () => {
  const html = render()
  assert.match(html, /Message preview/)
  assert.doesNotMatch(html, /Total SMS segments|Estimated total cost|Eligible recipients|GSM-7|4 customer/)
  assert.doesNotMatch(html, /<details|<summary/)
})
test('default is first recipient; a native selector switches the personalised bubble immediately', () => {
  const original = structuredClone(preview)
  assert.equal(previewRecipient(preview).id, 'sarah')
  assert.equal(previewRecipient(preview, 'removed-recipient').id, 'sarah')
  let selectedId
  const tree = SMSPreviewLayout({ preview, onSelect: id => { selectedId = id } })
  const select = elements(tree).find(element => element.type === 'select')
  assert.equal(select.props.value, 'sarah')
  select.props.onChange({ target: { value: 'jane' } })
  const html = render(preview, { selectedId })
  assert.ok(html.includes('Hi Jane!\n\nA different personalised message 😀'))
  assert.doesNotMatch(html, /Hi Sarah!/)
  assert.doesNotMatch(html, /UCS-2|44 characters|2 SMS segment/)
  assert.deepEqual(preview, original, 'Changing preview does not mutate content or campaign recipients')
})
test('paragraphs, line breaks and spaces come from the server body without substitutions', () => {
  const tree = SMSPreviewLayout({ preview })
  const bubble = elements(tree).find(element => element.props?.className === 'sms-message-bubble')
  assert.equal(bubble.props.children, preview.recipients[0].body)
  const html = render()
  assert.ok(html.includes('TRUMPS PLAZA\n\nHi Sarah!\n  Keep these spaces.\n\nReply STOP to opt out.'))
  assert.doesNotMatch(html, /GSM-7|73 characters/)
})
test('phone numbers are masked everywhere in the preview selector and bubble headings', () => {
  const html = render()
  for (const row of preview.recipients) {
    assert.ok(html.includes(row.name)); assert.ok(html.includes(row.phone.slice(-4)))
    assert.ok(!html.includes(row.phone))
  }
  assert.equal(maskedPreviewPhone(null), 'Phone unavailable')
  assert.equal(maskedPreviewPhone('+353831234567'), '•••• ••• 4567')
})
test('empty and absent previews show safe states without a selector or invented message', () => {
  assert.equal(renderToStaticMarkup(h(SMSPreview, { preview: null })), '')
  const empty = { ...preview, recipients: [], recipient_count: 0, total_segments: 0, estimated_cost_micros: 0 }
  assert.equal(previewRecipient(empty), null)
  const html = render(empty)
  assert.match(html, /No eligible recipients to preview/)
  assert.doesNotMatch(html, /€0.00/); assert.doesNotMatch(html, /<select|sms-message-bubble/)
})
test('unsafe text is escaped and new snapshots get a fresh default selection', () => {
  const unsafe = { ...preview, recipients: [{ ...preview.recipients[0], name: '<script>Sarah</script>', body: '<script>never execute</script>\n\nHi!' }] }
  const html = render(unsafe)
  assert.match(html, /&lt;script&gt;/); assert.doesNotMatch(html, /<script>/)
  const wrapper = SMSPreview({ preview })
  assert.equal(wrapper.key, 'preview-one')
  assert.notEqual(SMSPreview({ preview: { ...preview, campaign_id: 'preview-two' } }).key, wrapper.key)
})
test('responsive CSS preserves readable bubble text and accessible selector', () => {
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
  assert.match(css, /\.sms-message-bubble[^}]*white-space: pre-wrap;[^}]*overflow-wrap: anywhere/)
  assert.match(css, /\.sms-message-bubble[^}]*var\(--theme-primary\)/)
  assert.match(css, /@media \(max-width: 760px\)[^\n]*\.sms-preview-conversation \{ grid-template-columns: 1fr/)
  const html = render()
  assert.match(html, /for="sms-preview-recipient"/); assert.match(html, /aria-controls="sms-preview-message"/)
  assert.match(html, /aria-live="polite"/)
})
test('confirmation uses original campaign and audience irrespective of the viewed recipient', async () => {
  const calls = []
  const flow = createSMSFlow({ role: 'OWNER', request: async (path, options) => { calls.push([path, options]); return path.endsWith('/confirm') ? { ...preview, status: 'QUEUED' } : preview } })
  await flow.preview({ audience: 'all', message: 'original template' })
  previewRecipient(flow.getSnapshot().preview, 'jane')
  assert.equal(await flow.confirm(false), false)
  assert.equal(calls.length, 1)
  assert.equal(await flow.confirm(true), true)
  assert.equal(calls[1][0], '/sms/campaigns/preview-one/confirm')
  assert.deepEqual(JSON.parse(calls[1][1].body), { confirmed: true })
  assert.equal(flow.getSnapshot().history[0].recipient_count, 2)
  const source = readFileSync(new URL('../src/components/SMSMessaging.jsx', import.meta.url), 'utf8')
  assert.match(source, /SMSConfirmation preview=\{state.preview\}/)
  assert.match(source, /busy=\{state.busy\}/)
  assert.match(source, /flow.confirm\(true\)/)
  assert.match(source, /No real text messages will be sent/)
})
