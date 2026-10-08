export const ticketNames = { DAILY_RAFFLE: 'Daily Raffle ticket', LOYALTY_10: '€10 Loyalty Voucher ticket', BIRTHDAY_20: '€20 Birthday Voucher ticket' }
export function printStatus(job) {
  return { PENDING: 'Queued', CLAIMED: 'Claimed', PRINTING: 'Printing', COMPLETED: 'Printed', RETRYABLE: 'Retryable', FAILED: 'Failed', UNCERTAIN: 'Uncertain — operator review required' }[job.status] || 'Status unavailable'
}
export function createPrintFlow({ request, newId = () => crypto.randomUUID() }) {
  let state = { jobs: null, detail: null, busy: false, error: '', notice: '' }
  let generation = 0; let pendingReprint = null
  const listeners = new Set()
  const publish = value => { state = value; listeners.forEach(listener => listener()) }
  return {
    getSnapshot: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    cancel() { generation++; state = { jobs: null, detail: null, busy: false, error: '', notice: '' } },
    async load(customerId, review = false) {
      const attempt = ++generation
      publish({ ...state, jobs: null, detail: null, busy: true, error: '' })
      try {
        const jobs = await request(customerId ? `/customers/${encodeURIComponent(customerId)}/print-jobs` : `/print-jobs${review ? '?review=true' : ''}`, { cache: 'no-store' })
        if (attempt === generation) publish({ ...state, jobs, busy: false })
      } catch (error) { if (attempt === generation) publish({ ...state, busy: false, error: error.message }) }
    },
    async inspect(jobId) {
      if (state.busy) return
      const attempt = ++generation
      pendingReprint = null
      publish({ ...state, busy: true, detail: null, error: '', notice: '' })
      try {
        const detail = await request(`/print-jobs/${encodeURIComponent(jobId)}`, { cache: 'no-store' })
        if (attempt === generation) publish({ ...state, detail, busy: false })
      } catch (error) { if (attempt === generation) publish({ ...state, busy: false, error: error.message }) }
    },
    async reprint(jobId, reason, confirmed) {
      if (state.busy) return false
      if (!confirmed || reason.trim().length < 5) { publish({ ...state, error: 'Confirm reprint and provide an audit reason (at least 5 characters).' }); return false }
      const attempt = ++generation
      const key = `${jobId}:${reason.trim()}`
      if (pendingReprint?.key !== key) pendingReprint = { key, requestId: newId() }
      publish({ ...state, busy: true, error: '', notice: '' })
      try {
        const result = await request(`/print-jobs/${encodeURIComponent(jobId)}/reprint`, { method: 'POST', body: JSON.stringify({ request_id: pendingReprint.requestId, reason: reason.trim(), confirmed: true }), cache: 'no-store' })
        if (attempt === generation) {
          publish({ ...state, busy: false, jobs: [result, ...(state.jobs || []).filter(job => job.print_job_id !== result.print_job_id)], notice: 'Reprint queued. No new reward was issued.' })
          pendingReprint = null; return true
        }
      } catch (error) { if (attempt === generation) publish({ ...state, busy: false, error: error.message }) }
      return false
    },
    async review(jobId) {
      if (state.busy) return
      const attempt = ++generation
      publish({ ...state, busy: true, error: '', notice: '' })
      try {
        const detail = await request(`/print-jobs/${encodeURIComponent(jobId)}/review`, { method: 'POST', body: '{}', cache: 'no-store' })
        if (attempt === generation) publish({ ...state, busy: false, detail, jobs: state.jobs?.map(job => job.print_job_id === jobId ? detail : job), notice: 'Expired lease reviewed. No ticket was printed.' })
      } catch (error) { if (attempt === generation) publish({ ...state, busy: false, error: error.message }) }
    },
  }
}
