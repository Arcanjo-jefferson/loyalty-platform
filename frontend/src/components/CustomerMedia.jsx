import { useCallback, useEffect, useRef, useState } from 'react'
import { customerRequest } from '../api'
import { useAuth } from '../AuthContext'
import { DOCUMENT_TYPES, mediaCategories, validateMediaFile } from '../media'
import ImageCapture from './ImageCapture'
import Notification from './Notification'

const titles = { 'profile-photo': 'Profile photo', 'id-document': 'Identity document', 'consent-evidence': 'Consent evidence' }
export default function CustomerMedia({ customer }) {
  const { user } = useAuth()
  return <div className="customer-media">{mediaCategories(user.role).map(kind => <MediaCard key={`${customer.customer_id}:${kind}`} customer={customer} kind={kind} />)}</div>
}
function MediaCard({ customer, kind }) {
  const [metadata, setMetadata] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [file, setFile] = useState(null)
  const [documentType, setDocumentType] = useState('Passport')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [imageUrl, setImageUrl] = useState('')
  const [reset, setReset] = useState(0)
  const [retry, setRetry] = useState(0)
  const requestGeneration = useRef(0)
  const advanceRequest = useCallback(() => ++requestGeneration.current, [])
  const path = `/${encodeURIComponent(customer.customer_id)}/${kind}`
  function clearImage() { setImageUrl('') }
  useEffect(() => () => { if (imageUrl) URL.revokeObjectURL(imageUrl) }, [imageUrl])
  useEffect(() => {
    const attempt = advanceRequest()
    customerRequest(path, { cache: 'no-store' }).then(data => {
      if (requestGeneration.current === attempt) { setMetadata(data); if (data.document_type) setDocumentType(data.document_type) }
    }).catch(err => { if (requestGeneration.current === attempt && err.status !== 404) setError(err.message) }).finally(() => { if (requestGeneration.current === attempt) setLoading(false) })
    return () => { advanceRequest() }
  }, [path, retry, advanceRequest])
  async function view() {
    const attempt = requestGeneration.current
    setBusy(true); setError('')
    try {
      const blob = await customerRequest(`${path}/image?revision=${encodeURIComponent(metadata.revision)}`, { responseType: 'blob', cache: 'no-store' })
      if (requestGeneration.current === attempt) { clearImage(); const url = URL.createObjectURL(blob); setImageUrl(url) }
    } catch (err) { if (requestGeneration.current === attempt) setError(err.message) }
    finally { if (requestGeneration.current === attempt) setBusy(false) }
  }
  async function upload(event) {
    event.preventDefault()
    const message = validateMediaFile(file)
    if (message) { setError(message); return }
    const attempt = requestGeneration.current
    setBusy(true); setError(''); setNotice('')
    try {
      const query = kind === 'id-document' ? `?document_type=${encodeURIComponent(documentType)}` : ''
      const saved = await customerRequest(path + query, { method: 'POST', body: file, headers: { 'Content-Type': file.type }, cache: 'no-store' })
      if (requestGeneration.current !== attempt) return
      clearImage(); setMetadata(saved); setFile(null); setReset(value => value + 1)
      setNotice(saved.cleanup_pending ? 'Image saved. Previous image cleanup is pending; contact your administrator.' : `${titles[kind]} saved successfully.`)
    } catch (err) { if (requestGeneration.current === attempt) setError(err.message === 'Failed to fetch' ? 'Cannot reach the API. Please try again.' : err.message) }
    finally { if (requestGeneration.current === attempt) setBusy(false) }
  }
  async function verify(status) {
    const attempt = requestGeneration.current
    setBusy(true); setError(''); setNotice('')
    try {
      const saved = await customerRequest(`${path}/verification`, { method: 'PATCH', body: JSON.stringify({ revision: metadata.revision, status }) })
      if (requestGeneration.current === attempt) { setMetadata(saved); setNotice(`Identity document marked ${status.toLowerCase()}.`) }
    } catch (err) { if (requestGeneration.current === attempt) setError(err.message) }
    finally { if (requestGeneration.current === attempt) setBusy(false) }
  }
  return <section className="panel media-card" aria-label={titles[kind]}><h2>{titles[kind]}</h2>
    {kind === 'consent-evidence' && <p>Signed evidence supports the customer’s recorded marketing consent; it does not change consent status.</p>}
    <Notification message={error} variant="error" /><Notification message={notice} onDismiss={() => setNotice('')} />
    {loading ? <p role="status">Loading image information…</p> : <>
      {metadata ? <><p>Uploaded {new Date(metadata.uploaded_at).toLocaleString('en-IE')}{metadata.document_type && ` · ${metadata.document_type}`}</p>{metadata.verification_status && <p>Verification: <strong>{metadata.verification_status}</strong>{metadata.verified_at && ` · ${new Date(metadata.verified_at).toLocaleString('en-IE')}`}</p>}
        <div className="media-actions"><button type="button" className="secondary" disabled={busy} onClick={view}>View current image</button>{imageUrl && <button type="button" className="secondary" onClick={clearImage}>Hide image</button>}</div>
        {imageUrl && <img className="media-image" src={imageUrl} alt={`Current customer ${titles[kind].toLowerCase()}`} />}
        {kind === 'id-document' && <div className="media-actions"><button type="button" className="secondary" disabled={busy} onClick={() => verify('Verified')}>Mark verified</button><button type="button" className="secondary" disabled={busy} onClick={() => verify('Rejected')}>Mark rejected</button></div>}
      </> : <p>No image uploaded.</p>}
      {error && <button type="button" className="secondary" disabled={busy} onClick={() => { clearImage(); setError(''); setLoading(true); setRetry(value => value + 1) }}>Reload image information</button>}
      <form onSubmit={upload}><fieldset disabled={busy}>
        {kind === 'id-document' && <label>Document type<select value={documentType} onChange={event => setDocumentType(event.target.value)}>{DOCUMENT_TYPES.map(type => <option key={type}>{type}</option>)}</select></label>}
        <ImageCapture key={reset} onSelect={setFile} disabled={busy} label={titles[kind]} />
        <small>JPEG, PNG or WebP · Maximum 5 MiB · Use fictional documents during development.</small>
        <button type="submit" className="primary" disabled={busy || !file}>{busy ? 'Saving…' : metadata ? 'Replace image' : 'Upload image'}</button>
      </fieldset></form>
    </>}
  </section>
}
