import { createElement as h } from 'react'

// Kept separate from loading so every image/placeholder state can be rendered
// and tested without real credentials or a browser camera.
export default function ProfileAvatar({ customer, photo, onRetry, onImageError }) {
  const name = `${customer.first_name} ${customer.last_name}`
  const message = photo.status === 'loading' ? 'Loading profile photo…' : photo.status === 'error' ? 'Profile photo unavailable.' : photo.status === 'empty' ? 'No profile photo' : ''
  return h('div', { className: 'profile-avatar-block' },
    photo.status === 'ready'
      ? h('img', { className: 'profile-avatar', src: photo.url, alt: `Profile photo of ${name}`, onError: onImageError })
      : h('div', { className: 'profile-avatar profile-avatar-placeholder', 'aria-label': `Avatar for ${name}` }, `${customer.first_name[0]}${customer.last_name[0]}`),
    message && h('small', { role: photo.status === 'empty' ? undefined : 'status' }, message),
    photo.status === 'error' && h('button', { type: 'button', className: 'text-button', onClick: onRetry }, 'Retry photo'),
  )
}
