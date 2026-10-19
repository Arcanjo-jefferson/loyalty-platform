import { createElement as h } from 'react'
import { smsMoney } from '../smsFlow.js'
import SMSPreview from './SMSPreview.js'

export default function SMSConfirmation({ preview, busy, onConfirm, onBack }) {
  return h('section', { className: 'sms-send-confirm', 'aria-label': 'Confirm send' },
    h('p', null, 'Send this message to ', h('strong', null, `${preview.recipient_count} eligible customer${preview.recipient_count === 1 ? '' : 's'}`), '?'),
    h('p', null, 'Estimated total cost: ', h('strong', null, smsMoney(preview.estimated_cost_micros))),
    h('p', { className: 'muted' }, 'This is a simulation. The cost is an estimate; you will not be charged.'),
    h(SMSPreview, { preview }),
    h('div', { className: 'sms-compose-actions' },
      h('button', { className: 'primary', type: 'button', disabled: busy || !preview.recipient_count, onClick: onConfirm }, busy ? 'Please wait…' : 'Yes, confirm send'),
      h('button', { className: 'secondary', type: 'button', disabled: busy, onClick: onBack }, 'Go back')))
}
