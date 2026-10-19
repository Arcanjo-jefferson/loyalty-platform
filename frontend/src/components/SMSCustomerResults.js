import { createElement as h } from 'react'

export default function SMSCustomerResults({ query, results, loading, error, total, selected, onSelect, onRetry, disabled }) {
  return h('div', { className: 'sms-customer-search', 'aria-busy': loading },
    h('div', { role: 'status', 'aria-live': 'polite' },
      loading ? 'Searching customers…' : !query.trim() ? 'Type a name or Irish phone number to find a customer.'
        : error ? null : !results.length ? 'No matching customers. Try another name or phone number.'
          : `${total} matching customer(s)${total > results.length ? `; showing ${results.length}. Refine your search for more.` : '.'}`),
    error && h('div', null, h('p', { role: 'alert' }, error), h('button', { type: 'button', className: 'secondary', disabled, onClick: onRetry }, 'Retry customer search')),
    !loading && !error && results.length > 0 && h('ul', { className: 'sms-customer-results', 'aria-label': 'Matching customers' },
      ...results.map(customer => h('li', { key: customer.customer_id },
        h('button', { type: 'button', className: `sms-customer-result${selected?.customer_id === customer.customer_id ? ' is-selected' : ''}`,
          disabled: disabled || !customer.sms_eligible, 'aria-pressed': selected?.customer_id === customer.customer_id,
          onClick: () => onSelect(customer.customer_id) },
          h('span', { className: 'sms-result-identity' }, h('strong', null, customer.name), h('span', null, customer.masked_phone)),
          h('span', { className: 'sms-result-eligibility' }, customer.sms_eligible ? 'Eligible for SMS' : customer.ineligible_reason))))))
}
