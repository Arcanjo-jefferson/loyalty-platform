import { createElement as h } from 'react'
import { voucherLabel, voucherStatus } from '../voucherFlow.js'

const dublinTime = value => value ? new Date(value).toLocaleString('en-IE', { timeZone: 'Europe/Dublin' }) : '—'

// Presentation only: the shared voucher flow supplies the current voucher status.
export default function VoucherCard({ voucher, busy, onRedeem }) {
  const status = voucherStatus(voucher)
  const fields = [
    ['Code', voucher.voucher_code, 'voucher-code'], ['Status', status],
    ['Value', new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR' }).format(voucher.value_cents / 100)],
    ['Issued', dublinTime(voucher.issued_at)], ['Expires', `${dublinTime(voucher.expires_at)} (Dublin)`],
    ...(voucher.redeemed_at ? [['Redeemed', dublinTime(voucher.redeemed_at)]] : []),
  ]
  return h('article', { className: 'voucher-card' },
    h('h3', null, voucherLabel(voucher)),
    h('dl', null, fields.map(([label, value, className]) => h('div', { key: label }, h('dt', null, label), h('dd', { className }, value)))),
    status === 'ACTIVE'
      ? h('button', { className: 'primary', type: 'button', disabled: busy, onClick: () => onRedeem(voucher) }, 'Redeem voucher')
      : status === 'REDEEMED'
        ? h('p', { className: 'voucher-state voucher-state-redeemed' }, h('span', { 'aria-hidden': true }, '✓ '), 'Redeemed')
        : status === 'EXPIRED' ? h('p', { className: 'voucher-state' }, 'Expired') : null,
  )
}
