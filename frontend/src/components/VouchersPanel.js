import { createElement as h } from 'react'
import VoucherCard from './VoucherCard.js'
import { effectiveVoucher } from '../voucherFlow.js'

// The single render path for both customer profiles and standalone lookup.
export default function VouchersPanel({ customerId, state, code, now, onCodeChange, onLookup, onRefresh, onRedeem, notifications }) {
  return h('section', { className: 'panel vouchers', 'aria-label': customerId ? 'Customer vouchers' : 'Voucher lookup and redemption' },
    h('div', { className: 'vouchers-content' },
      h('h2', null, 'Vouchers'),
      customerId
        ? h('button', { type: 'button', className: 'secondary', disabled: state.busy, onClick: onRefresh }, 'Refresh vouchers')
        : h('form', { onSubmit: event => { event.preventDefault(); onLookup() } },
          h('label', null, 'Voucher code', h('input', { value: code, maxLength: 100, autoComplete: 'off', disabled: state.busy, onChange: event => onCodeChange(event.target.value) })),
          h('button', { className: 'primary', disabled: state.busy || !code.trim() }, 'Look up voucher')),
      notifications,
      state.busy && h('p', { role: 'status' }, 'Loading voucher information…'),
      state.loaded && !state.error && !state.vouchers.length && h('p', null, 'No vouchers issued.'),
      h('div', { className: 'voucher-grid' }, state.vouchers.map(raw => h(VoucherCard, { key: raw.voucher_id, voucher: effectiveVoucher(raw, now), busy: state.busy, onRedeem }))),
    ),
  )
}
