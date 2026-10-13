import { createElement as h, useState } from 'react'
export default function BrandIdentity({ branding, compact = false }) {
  const [failed, setFailed] = useState(false)
  return h('span', { className: `brand-identity${compact ? ' brand-identity--compact' : ''}` },
    branding.logo && !failed ? h('img', { className: 'business-logo', src: branding.logo, alt: `${branding.name} logo`, onError: () => setFailed(true) }) : null,
    h('span', { className: 'brand-title-group' },
      h('span', { className: 'wordmark' }, 'Loyalty System'),
      compact && h('span', { className: 'developer-credit' }, 'Developed by ',
        h('span', { className: 'developer-credit-name' }, 'Avtronics'))))
}
