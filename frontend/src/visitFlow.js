import { searchCustomers } from './customerSearch.js'
import { visitSuccessMessages } from './raffleFlow.js'
// Lookup never records a visit; the separate confirmation call is explicit.
export function createVisitFlow({ request }) {
  const initial = () => ({ stage: 'idle', result: null, matches: null, error: '', notice: '' })
  let snapshot = initial()
  let generation = 0
  const listeners = new Set()
  function publish(value) { snapshot = value; listeners.forEach(listener => listener()) }
  const busy = () => ['looking-up', 'searching', 'confirming'].includes(snapshot.stage)
  return {
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    clear() { if (!busy()) { generation++; publish(initial()) } },
    cancel() { generation++; snapshot = initial() },
    async search(query) {
      if (busy()) return
      const attempt = ++generation
      if (!query.trim()) { publish({ ...initial(), error: 'Enter a customer name or phone number.' }); return }
      publish({ ...initial(), stage: 'searching' })
      try {
        const customers = await request('/customers', { cache: 'no-store' })
        if (generation === attempt) publish({ ...initial(), stage: 'search-results', matches: searchCustomers(customers, query) })
      } catch (error) {
        if (generation === attempt) publish({ ...initial(), error: error.message === 'Failed to fetch' ? 'Cannot search customers. Please try again.' : error.message })
      }
    },
    async select(customerId) {
      if (busy()) return
      const candidate = snapshot.matches?.find(customer => customer.customer_id === customerId)
      if (!candidate) return
      if (candidate.status !== 'active') { publish({ ...snapshot, result: null, stage: 'search-results', error: 'Inactive customers cannot register visits.', notice: '' }); return }
      const attempt = ++generation
      const matches = snapshot.matches
      publish({ stage: 'looking-up', matches, result: null, error: '', notice: '' })
      try {
        // Same read-only customer/progress endpoint used by the profile. No write on selection.
        const result = await request(`/customers/${encodeURIComponent(customerId)}/visits`, { cache: 'no-store' })
        if (result.customer.status !== 'active') throw Error('Inactive customers cannot register visits.')
        if (generation === attempt) publish({ stage: 'ready', matches, result, error: '', notice: '' })
      } catch (error) {
        if (generation === attempt) publish({ stage: 'search-results', matches, result: null, error: error.status === 404 ? 'Customer is unavailable. Search again.' : error.message === 'Failed to fetch' ? 'Cannot load customer details. Please try again.' : error.message, notice: '' })
      }
    },
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
        if (generation === attempt) publish({ stage: 'confirmed', result, error: '', notice: visitSuccessMessages(result).join(' ') })
      } catch (error) {
        if (generation === attempt) publish({ stage: 'ready', result: before, error: error.message === 'Failed to fetch' ? 'Cannot reach the API. Please try again.' : error.message, notice: '' })
      }
    },
  }
}
