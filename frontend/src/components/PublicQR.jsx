import { useState } from 'react'
import { publicQRReference } from '../qrFlow'
import PublicQRView from './PublicQRView.js'

export default function PublicQR() {
  const reference = publicQRReference(window.location.pathname)
  const [failed, setFailed] = useState(!reference)
  const [loaded, setLoaded] = useState(false)
  const base = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
  return <PublicQRView imageUrl={reference ? `${base}/public/qr/${reference}/image` : undefined} failed={failed} loaded={loaded} onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
}
