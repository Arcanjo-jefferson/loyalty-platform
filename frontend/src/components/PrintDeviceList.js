import { createElement as h } from 'react'

export function deviceLastSeen(value) {
  if (!value) return 'Never seen'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? 'Unavailable' : new Intl.DateTimeFormat('en-IE', { dateStyle: 'medium', timeStyle: 'short' }).format(date)
}

export default function PrintDeviceList({ devices, busy, onAction }) {
  if (!devices) return null
  if (!devices.length) return h('p', null, 'No print devices registered yet.')
  return h('ul', { className: 'device-list', 'aria-label': 'Registered print devices' }, devices.map(device =>
    h('li', { key: device.device_id, className: 'device-card' },
      h('h3', null, device.label),
      h('dl', null,
        h('div', null, h('dt', null, 'Status'), h('dd', null, device.status)),
        h('div', null, h('dt', null, 'Device ID'), h('dd', { className: 'device-id' }, device.device_id)),
        h('div', null, h('dt', null, 'Last seen'), h('dd', null, deviceLastSeen(device.last_seen)))),
      h('div', { className: 'device-actions' },
        h('button', { type: 'button', className: 'secondary', disabled: busy || device.status === 'DISABLED', onClick: () => onAction(device, 'disable'), 'aria-label': `Disable ${device.label}` }, 'Disable'),
        h('button', { type: 'button', className: 'secondary', disabled: busy || device.status === 'PENDING_PROVISIONING', onClick: () => onAction(device, 'rotate'), 'aria-label': `Request rotation for ${device.label}` }, 'Request rotation')))))
}
