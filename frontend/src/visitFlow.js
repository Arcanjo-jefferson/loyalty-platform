// Lookup never records a visit; the separate confirmation call is explicit.
export function createVisitFlow({ request }) {
  let snapshot = { stage: 'idle', result: null, error: '', notice: '' }
  let generation = 0
  const listeners = new Set()
  function publish(value) { snapshot = value; listeners.forEach(listener => listener()) }
  const busy = () => snapshot.stage === 'looking-up' || snapshot.stage === 'confirming'
  return {
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    clear() { if (!busy()) { generation++; publish({ stage: 'idle', result: null, error: '', notice: '' }) } },
    cancel() { generation++; snapshot = { stage: 'idle', result: null, error: '', notice: '' } },
    async lookup(scanned) {
      if (busy()) return
      const attempt = ++generation
      const token = scanned.trim()
      if (!/^[A-Za-z0-9_-]{16,128}$/.test(token)) { publish({ stage: 'idle', result: null, error: 'Scan or enter a valid customer QR token.', notice: '' }); return }
      publish({ stage: 'looking-up', result: null, error: '', notice: '' })
      try {
        const result = await request('/loyalty/lookup', { method: 'POST', body: JSON.stringify({ qr_token: token }), cache: 'no-store' })
        if (generation === attempt) publish({ stage: 'ready', result, error: '', notice: '' })
      } catch (error) {
        if (generation === attempt) publish({ stage: 'idle', result: null, error: error.status === 404 ? 'No active customer matches this QR token.' : error.message === 'Failed to fetch' ? 'Cannot reach the API. Please try again.' : error.message, notice: '' })
      }
    },
    async confirm() {
      if (snapshot.stage !== 'ready' || !snapshot.result) return
      const attempt = ++generation
      const before = snapshot.result
      publish({ stage: 'confirming', result: before, error: '', notice: '' })
      try {
        const result = await request(`/customers/${encodeURIComponent(before.customer.customer_id)}/visits`, { method: 'POST', body: '{}', cache: 'no-store' })
        if (generation === attempt) publish({ stage: 'confirmed', result, error: '', notice: result.reward_earned ? 'Visit recorded successfully. €10 reward earned.' : 'Visit recorded successfully.' })
      } catch (error) {
        if (generation === attempt) publish({ stage: 'ready', result: before, error: error.message === 'Failed to fetch' ? 'Cannot reach the API. Please try again.' : error.message, notice: '' })
      }
    },
  }
}
