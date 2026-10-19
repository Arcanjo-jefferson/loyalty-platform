import { createElement as h } from 'react'

const choices = [
  ['individual', '♙', 'Individual Customer', 'Find and select one customer for a personalised message.'],
  ['all', '♙♙', 'All Eligible Customers', 'Message active customers with valid consent who have not opted out.'],
]
export default function SMSAudienceCards({ value, onChange, disabled }) {
  return h('fieldset', { className: 'sms-audience-group', disabled },
    h('legend', null, 'Choose recipients'),
    h('div', { className: 'sms-audience-cards' }, ...choices.map(([id, icon, title, description]) =>
      h('label', { key: id, className: `sms-audience-card${value === id ? ' is-selected' : ''}` },
        h('input', { type: 'radio', name: 'sms-audience', value: id, checked: value === id,
          onChange: () => onChange(id), 'aria-describedby': `sms-audience-${id}-description` }),
        h('span', { className: 'sms-audience-icon', 'aria-hidden': true }, icon),
        h('span', { className: 'sms-audience-copy' }, h('strong', null, title),
          h('span', { id: `sms-audience-${id}-description` }, description))))))
}
