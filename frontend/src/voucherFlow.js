export const voucherStatus = voucher => String(voucher.status || '').trim().toUpperCase()
export function effectiveVoucher(voucher, now = Date.now()) {
  const status = voucherStatus(voucher)
  return { ...voucher, status: status === 'ACTIVE' && now >= Date.parse(voucher.expires_at) ? 'EXPIRED' : status }
}
export const voucherLabel = voucher => voucher.type === 'LOYALTY_10' ? '€10 Loyalty Voucher' : '€20 Birthday Voucher'
export function rewardMessages(vouchers = []) {
  return vouchers.map(v => v.type === 'LOYALTY_10' ? '€10 Loyalty Voucher earned' : '€20 Birthday Voucher issued')
}
export function createVoucherFlow({ request, clock = Date.now }) {
  let snapshot = { vouchers: [], busy: false, loaded: false, error: '', notice: '' }
  let generation = 0
  const listeners = new Set()
  const publish = value => { snapshot = value; listeners.forEach(listener => listener()) }
  async function read(path, options) {
    if (snapshot.busy) return
    const attempt = ++generation
    publish({ vouchers: [], busy: true, loaded: false, error: '', notice: '' })
    try {
      const data = await request(path, { ...options, cache: 'no-store' })
      if (generation === attempt) publish({ vouchers: (Array.isArray(data) ? data : [data]).map(v => effectiveVoucher(v, clock())), busy: false, loaded: true, error: '', notice: '' })
    } catch (error) {
      if (generation === attempt) publish({ vouchers: [], busy: false, loaded: true, error: error.message === 'Failed to fetch' ? 'Cannot reach the API. Please try again.' : error.message, notice: '' })
    }
  }
  return {
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    clear() { if (!snapshot.busy) { generation++; publish({ vouchers: [], busy: false, loaded: false, error: '', notice: '' }) } },
    cancel() { generation++; snapshot = { vouchers: [], busy: false, loaded: false, error: '', notice: '' } },
    load(customerId) { return read(`/customers/${encodeURIComponent(customerId)}/vouchers`) },
    lookup(code) { return read('/vouchers/lookup', { method: 'POST', body: JSON.stringify({ voucher_code: code.trim() }) }) },
    async redeem(voucher) {
      if (snapshot.busy || !snapshot.vouchers.some(v => v.voucher_id === voucher.voucher_id && v.customer_id === voucher.customer_id)) return
      if (effectiveVoucher(voucher, clock()).status !== 'ACTIVE') {
        publish({ ...snapshot, error: 'This voucher has expired or has already been redeemed.', notice: '' }); return
      }
      const attempt = ++generation
      publish({ ...snapshot, busy: true, error: '', notice: '' })
      try {
        const saved = await request(`/customers/${encodeURIComponent(voucher.customer_id)}/vouchers/${encodeURIComponent(voucher.voucher_id)}/redeem`, { method: 'POST', body: '{}', cache: 'no-store' })
        if (generation === attempt) publish({ ...snapshot, vouchers: snapshot.vouchers.map(v => v.voucher_id === saved.voucher_id ? saved : v), busy: false, notice: 'Voucher redeemed successfully.' })
      } catch (error) {
        // Reload server status after a conflict, including redemption in another tab.
        let vouchers = snapshot.vouchers
        if (error.status === 409) {
          try {
            const fresh = await request('/vouchers/lookup', { method: 'POST', body: JSON.stringify({ voucher_code: voucher.voucher_code }), cache: 'no-store' })
            vouchers = vouchers.map(v => v.voucher_id === fresh.voucher_id ? effectiveVoucher(fresh, clock()) : v)
          } catch { /* Original error remains visible; no success is shown. */ }
        }
        if (generation === attempt) publish({ ...snapshot, vouchers, busy: false, error: error.message === 'Failed to fetch' ? 'Cannot reach the API. Check the voucher status before retrying.' : error.message, notice: '' })
      }
    },
  }
}
