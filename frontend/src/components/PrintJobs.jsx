import { useEffect, useState, useSyncExternalStore } from 'react'
import { apiRequest } from '../api'
import { useAuth } from '../AuthContext'
import { createPrintFlow, printStatus } from '../printFlow'
import PrintJobStatuses from './PrintJobStatuses.js'
import Notification from './Notification'

export default function PrintJobs({ customerId }) {
  const { user } = useAuth()
  const canManage = ['OWNER', 'MANAGER'].includes(user.role)
  const [flow] = useState(() => createPrintFlow({ request: apiRequest }))
  const state = useSyncExternalStore(flow.subscribe, flow.getSnapshot)
  const [reviewOnly, setReviewOnly] = useState(false)
  const [reason, setReason] = useState('')
  const [confirmed, setConfirmed] = useState(false)
  useEffect(() => {
    if (!customerId && !canManage) return
    flow.load(customerId, reviewOnly)
    return () => flow.cancel()
  }, [flow, customerId, reviewOnly, canManage])
  if (!customerId && !canManage) return <p role="alert">Only Owner and Manager may administer the print queue.</p>
  const detail = state.detail
  const reprintable = detail && !detail.reprint_of && ['COMPLETED', 'FAILED', 'UNCERTAIN'].includes(detail.status)
  return <section className="panel print-jobs"><h2>{customerId ? 'Ticket print status' : 'Print queue'}</h2>
    <p>Tickets are queued digitally. Spool submission does not confirm physical output.{customerId && ' Showing the ten most recent jobs.'}</p>
    {!customerId && <label className="print-checkbox"><input type="checkbox" checked={reviewOnly} onChange={event => setReviewOnly(event.target.checked)} />Show only jobs that need attention</label>}
    <button type="button" className="secondary" disabled={state.busy} onClick={() => flow.load(customerId, reviewOnly)}>Refresh print status</button>
    <Notification message={state.error} variant="error" /><Notification message={state.notice} />
    {state.busy && <p role="status">Loading print jobs…</p>}
    <PrintJobStatuses jobs={customerId ? state.jobs?.slice(0, 10) : state.jobs} busy={state.busy} onInspect={canManage ? jobId => { setReason(''); setConfirmed(false); flow.inspect(jobId) } : undefined} />
    {canManage && detail && <div className="ticket-review"><h3>{printStatus(detail)}</h3><p>{detail.last_error || 'No recorded error.'}</p>
      <pre className="ticket-preview" aria-label="Immutable receipt ticket preview">{detail.ticket.receipt_text}</pre>
      {['UNCERTAIN', 'RETRYABLE', 'FAILED'].includes(detail.status) && detail.lease_until && <button type="button" className="secondary" disabled={state.busy} onClick={() => flow.review(detail.print_job_id)}>Review expired lease</button>}
      {reprintable && <div className="reprint-controls"><p>An uncertain attempt may already have produced paper. Check the printer before explicitly authorizing another ticket.</p>
        <label>Reprint audit reason<textarea value={reason} maxLength={300} disabled={state.busy} onChange={event => setReason(event.target.value)} /></label>
        <label className="print-checkbox"><input type="checkbox" checked={confirmed} disabled={state.busy} onChange={event => setConfirmed(event.target.checked)} />I authorize an additional ticket marked REPRINT.</label>
        <button type="button" className="primary" disabled={state.busy || !confirmed || reason.trim().length < 5} onClick={async () => { if (await flow.reprint(detail.print_job_id, reason, confirmed)) { setReason(''); setConfirmed(false) } }}>Queue explicit reprint</button></div>}
    </div>}
  </section>
}
