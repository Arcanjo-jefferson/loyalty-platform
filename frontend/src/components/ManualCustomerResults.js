import { createElement as h } from 'react'

export default function ManualCustomerResults({ matches, busy, onSelect }) {
  if (!matches) return null
  if (!matches.length) return h('p', { role: 'status' }, 'No customers match this search.')
  return h('div', { 'aria-label': 'Customer search results' },
    h('p', { role: 'status' }, `${matches.length} matching ${matches.length === 1 ? 'customer' : 'customers'}. Select a customer to review before confirming.`),
    h('ul', { className: 'manual-customer-results' }, ...matches.map(customer => {
      const name = `${customer.first_name} ${customer.last_name}`
      return h('li', { key: customer.customer_id },
        h('div', null, h('strong', null, name), h('span', null, customer.phone), customer.status !== 'active' && h('span', null, 'Inactive')),
        h('button', { type: 'button', className: 'secondary', disabled: busy || customer.status !== 'active',
          'aria-label': `Select ${name}, ${customer.phone}`, onClick: () => onSelect(customer.customer_id) }, 'Select customer'))
    })))
}
