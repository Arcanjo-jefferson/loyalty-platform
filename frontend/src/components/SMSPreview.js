import { createElement as h, useState } from 'react'

export function maskedPreviewPhone(phone) {
  const digits = String(phone || '').replace(/\D/g, '')
  return digits.length >= 4 ? `•••• ••• ${digits.slice(-4)}` : 'Phone unavailable'
}

export function previewRecipient(preview, id) {
  return preview.recipients.find(row => row.id === id) || preview.recipients[0] || null
}

// Controlled presentation is shared by the interactive selector and render tests.
export function SMSPreviewLayout({ preview, selectedId, onSelect, sample = false }) {
  const selected = previewRecipient(preview, selectedId)
  return h('section', { className: 'sms-preview', 'aria-label': 'Message preview' },
    h('h3', null, 'Message preview'),
    selected ? h('div', { className: 'sms-preview-conversation' },
      preview.recipients.length > 1 && h('div', { className: 'sms-preview-selector' },
        h('label', { htmlFor: 'sms-preview-recipient' }, 'Preview for customer'),
        h('select', { id: 'sms-preview-recipient', value: selected.id, onChange: event => onSelect(event.target.value), 'aria-controls': 'sms-preview-message' },
          ...preview.recipients.map(row => h('option', { key: row.id, value: row.id }, `${row.name} · ${maskedPreviewPhone(row.phone)}`))),
        h('small', null, 'Choose a customer to see their message.')),
      h('div', { className: 'sms-preview-device' },
        h('div', { className: 'sms-preview-sender' }, h('span', null, 'SMS from'), h('strong', null, preview.sender)),
        h('div', { id: 'sms-preview-message', className: 'sms-preview-message', 'aria-live': 'polite', 'aria-atomic': true },
          h('p', { className: 'sms-preview-to' }, sample ? `Example for ${selected.name}` : `To ${selected.name} · ${maskedPreviewPhone(selected.phone)}`),
          // Render the exact server-authored body. No trimming, interpolation or reflow in JS.
          h('div', { className: 'sms-message-bubble' }, selected.body))))
      : h('div', { className: 'sms-preview-empty', role: 'status' }, 'No eligible recipients to preview. Choose another customer or check consent and SMS opt-outs.'))
}

function RecipientPreview({ preview, sample }) {
  const [selectedId, setSelectedId] = useState('')
  return h(SMSPreviewLayout, { preview, selectedId, onSelect: setSelectedId, sample })
}

export default function SMSPreview({ preview, sample = false }) {
  return preview ? h(RecipientPreview, { key: preview.campaign_id, preview, sample }) : null
}
