export function customerQRLink(reference, base) {
  if (!/^[A-Za-z0-9_-]{43}$/.test(reference)) throw Error('Invalid QR link reference.')
  const url = new URL(base)
  if (!['http:', 'https:'].includes(url.protocol)) throw Error('Invalid customer-facing URL configuration.')
  return `${url.origin}/q/${reference}`
}
export function publicQRReference(path) {
  return /^\/q\/([A-Za-z0-9_-]{43})\/?$/.exec(path)?.[1] || null
}
export function createQRFlow({ request }) {
  let state = { busy: false, details: null, error: '', notice: '' }
  const listeners = new Set(); let generation = 0
  const publish = value => { state = value; listeners.forEach(listener => listener()) }
  async function operation(path, body, notice) {
    if (state.busy) return
    const attempt = ++generation
    publish({ ...state, busy: true, error: '', notice: '' })
    try {
      const result = await request(path, { method: 'POST', body: JSON.stringify(body), cache: 'no-store' })
      if (generation === attempt) publish({ ...state, busy: false, details: result, notice })
    } catch (error) {
      if (generation === attempt) publish({ ...state, busy: false, error: error.message === 'Failed to fetch' ? 'Cannot reach the API. Please try again.' : error.message, notice: '' })
    }
  }
  return {
    getSnapshot: () => state,
    subscribe(callback) { listeners.add(callback); return () => listeners.delete(callback) },
    cancel() { generation++; state = { busy: false, details: null, error: '', notice: '' } },
    load(id) { return operation(`/customers/${encodeURIComponent(id)}/qr/link`, {}, '') },
    regenerate(id, confirmed) {
      if (!confirmed || !state.details) return
      return operation(`/customers/${encodeURIComponent(id)}/qr/regenerate`, { confirmed: true, expected_qr_token: state.details.qr_token }, 'QR regenerated. Previous QR and link are no longer valid.')
    },
    async send(id) {
      if (state.busy) return
      const attempt = ++generation
      publish({ ...state, busy: true, error: '', notice: '' })
      try {
        await request(`/customers/${encodeURIComponent(id)}/qr/send`, { method: 'POST', body: '{}', cache: 'no-store' })
        if (generation === attempt) publish({ ...state, busy: false, error: 'SMS delivery is not available yet.', notice: '' })
      } catch (error) { if (generation === attempt) publish({ ...state, busy: false, error: error.message, notice: '' }) }
    },
  }
}
