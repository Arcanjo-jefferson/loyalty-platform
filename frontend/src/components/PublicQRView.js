import { createElement as h } from 'react'

// Public presentation has no customer/profile object and no authenticated API.
export default function PublicQRView({ imageUrl, failed, loaded, onLoad, onError }) {
  return h('main', { className: 'public-qr' }, h('section', { className: 'panel customer-qr' },
    h('h1', null, 'Contactly'), h('h2', null, 'Your loyalty QR'),
    h('p', null, 'Show this QR when visiting. Staff will confirm your loyalty visit.'),
    failed ? h('p', { role: 'alert' }, 'This QR link is unavailable. Ask the business for your current link.')
      : h('div', null, h('img', { className: 'loyalty-qr-image', src: imageUrl, alt: 'Your loyalty QR', referrerPolicy: 'no-referrer', onLoad, onError }),
        !loaded && h('p', { role: 'status' }, 'Loading QR…')),
  ))
}
