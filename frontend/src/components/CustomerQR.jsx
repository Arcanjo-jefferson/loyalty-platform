import { useEffect, useState, useSyncExternalStore } from 'react'
import { apiRequest } from '../api'
import { useAuth } from '../AuthContext'
import { createQRFlow, customerQRLink } from '../qrFlow'
import Notification from './Notification'

export default function CustomerQR({ customer }) {
  const { user } = useAuth()
  const [flow] = useState(() => createQRFlow({ request: apiRequest }))
  const state = useSyncExternalStore(flow.subscribe, flow.getSnapshot)
  const [photo, setPhoto] = useState(null)
  const image = photo?.reference === state.details?.public_reference ? photo?.url || '' : ''
  const imageError = photo?.reference === state.details?.public_reference ? photo?.error || '' : ''
  const [confirm, setConfirm] = useState(false)
  const [copyMessage, setCopyMessage] = useState('')
  useEffect(() => { flow.load(customer.customer_id); return () => flow.cancel() }, [flow, customer.customer_id])
  useEffect(() => {
    if (!state.details) return
    let active = true; let url
    apiRequest(`/customers/${encodeURIComponent(customer.customer_id)}/qr/image`, { responseType: 'blob', cache: 'no-store' }).then(blob => {
      if (active) { url = URL.createObjectURL(blob); setPhoto({ reference: state.details.public_reference, url, error: '' }) }
    }).catch(error => { if (active) setPhoto({ reference: state.details.public_reference, url: '', error: error.message }) })
    return () => { active = false; if (url) URL.revokeObjectURL(url) }
  }, [customer.customer_id, state.details])
  async function copy() {
    try {
      await navigator.clipboard.writeText(customerQRLink(state.details.public_reference, import.meta.env.VITE_CUSTOMER_QR_BASE_URL || window.location.origin))
      setCopyMessage('QR link copied.')
    } catch { setCopyMessage('Unable to copy the QR link. Check clipboard permission and URL configuration.') }
  }
  return <section className="panel customer-qr" aria-label="Loyalty QR"><h2>Loyalty QR</h2><p>{customer.first_name} {customer.last_name}</p><p>Scan this QR to register a loyalty visit.</p>
    <Notification message={state.error || imageError} variant="error" /><Notification message={state.notice || copyMessage} />
    {image ? <img className="loyalty-qr-image" src={image} alt={`Loyalty QR for ${customer.first_name} ${customer.last_name}`} /> : <p role="status">{imageError ? 'QR image unavailable.' : 'Loading loyalty QR…'}</p>}
    <div className="qr-actions"><button className="secondary" disabled={state.busy || !state.details} onClick={copy}>Copy QR Link</button><button className="secondary" disabled={state.busy || !state.details} onClick={() => flow.send(customer.customer_id)}>Send QR Link</button>
      {['OWNER', 'MANAGER'].includes(user.role) && <button className="secondary" disabled={state.busy || !state.details} onClick={() => setConfirm(true)}>Regenerate QR</button>}
    </div><p className="qr-help">SMS sending is not configured yet. For a lost message, copy the existing link.</p>
    {confirm && <div className="qr-confirm" role="group" aria-label="Confirm QR regeneration"><p>Regenerate only for a compromised QR credential. The previous QR and public link will stop working immediately. Customer history and rewards will be preserved.</p><button className="primary" disabled={state.busy} onClick={async () => { setCopyMessage(''); await flow.regenerate(customer.customer_id, true); setConfirm(false) }}>Confirm regeneration</button><button className="secondary" disabled={state.busy} onClick={() => setConfirm(false)}>Cancel</button></div>}
    {(state.error || imageError) && <button className="secondary" disabled={state.busy} onClick={() => flow.load(customer.customer_id)}>Reload QR</button>}
  </section>
}
