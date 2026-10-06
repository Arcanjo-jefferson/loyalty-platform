import { useEffect, useState } from 'react'
import { customerRequest } from '../api'
import Notification from './Notification'

export default function CustomerVisits({ customerId }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    let active = true
    customerRequest(`/${encodeURIComponent(customerId)}/visits`, { cache: 'no-store' }).then(result => { if (active) setData(result) }).catch(err => { if (active) setError(err.message) })
    return () => { active = false }
  }, [customerId, retry])
  return <section className="panel customer-visits"><h2>Loyalty visits</h2><Notification message={error} variant="error" />
    {error && <button type="button" className="secondary" onClick={() => { setError(''); setRetry(value => value + 1) }}>Retry visit history</button>}
    {!data && !error && <p role="status">Loading visit history…</p>}
    {data && <><p><strong>Progress {data.progress} / 5</strong> · {data.total_visits} total visits · {data.visits_until_reward} until the next reward</p>{data.visits.length ? <ol>{[...data.visits].reverse().map(visit => <li key={visit.visit_id}>Visit {visit.visit_number} · {new Date(visit.visited_at).toLocaleString('en-IE')}</li>)}</ol> : <p>No visits recorded.</p>}</>}
    <a href="#/loyalty">Scan QR and confirm a visit</a>
  </section>
}
