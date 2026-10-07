import { useEffect, useState, useSyncExternalStore } from 'react'
import { apiRequest } from '../api'
import { createVisitFlow } from '../visitFlow'
import CustomerPhoto from './CustomerPhoto'
import ManualCustomerResults from './ManualCustomerResults.js'
import Notification from './Notification'
import { visitSuccessMessages } from '../raffleFlow'

export default function VisitScanner() {
  const [token, setToken] = useState('')
  const [query, setQuery] = useState('')
  const [flow] = useState(() => createVisitFlow({ request: apiRequest }))
  const state = useSyncExternalStore(flow.subscribe, flow.getSnapshot)
  useEffect(() => () => flow.cancel(), [flow])
  const busy = ['looking-up', 'searching', 'confirming'].includes(state.stage)
  const result = state.result
  return <section className="panel visit-scanner" aria-label="Record loyalty visit">
    <h2>Scan customer QR</h2><p>Use a keyboard scanner or enter the opaque QR token. Scanning identifies the customer; you must confirm to record a visit.</p><p>One loyalty visit per customer per calendar date (Europe/Dublin).</p>
    <form onSubmit={event => { event.preventDefault(); flow.lookup(token) }}><label>Customer QR token<input type="text" autoFocus autoComplete="off" spellCheck="false" value={token} disabled={busy} maxLength={128} onChange={event => { setToken(event.target.value); flow.clear() }} /></label><button className="primary" type="submit" disabled={busy || !token.trim()}>{state.stage === 'looking-up' ? 'Looking up…' : 'Look up customer'}</button></form>
    <p className="lookup-or">OR</p>
    <h2>Find customer</h2><p>Search by name or phone, select the correct customer, then confirm their visit.</p>
    <form onSubmit={event => { event.preventDefault(); flow.search(query) }}><label>Name or phone<input type="search" autoComplete="off" value={query} disabled={busy} maxLength={200} onChange={event => { setQuery(event.target.value); flow.clear() }} /></label><button className="primary" type="submit" disabled={busy || !query.trim()}>{state.stage === 'searching' ? 'Searching…' : 'Search'}</button></form>
    <ManualCustomerResults matches={state.matches} busy={busy} onSelect={customerId => flow.select(customerId)} />
    {state.stage === 'looking-up' && state.matches && <p role="status">Loading customer details…</p>}
    <Notification message={state.error} variant="error" /><Notification message={state.notice} />
    {result && <div className="visit-customer"><div className="profile-identity"><CustomerPhoto key={result.customer.customer_id} customer={result.customer} /><div><h2>{result.customer.first_name} {result.customer.last_name}</h2><p>{result.customer.phone}</p><a href={`#/customers/${result.customer.customer_id}`}>Open customer profile</a></div></div>
      <div className="loyalty-progress"><strong>Loyalty progress {result.progress} / 5</strong><progress max="5" value={result.progress} aria-label="Loyalty visits towards next reward" /><p>{result.total_visits} total visits · {result.visits_until_reward} visits until the next reward</p></div>
      {state.stage === 'confirmed' && visitSuccessMessages(result).map(message => <p className="reward-earned" key={message}>✓ {message}</p>)}
      {state.stage === 'confirmed' && result.vouchers?.length > 0 && <a href={`#/customers/${result.customer.customer_id}`}>View issued vouchers on customer profile</a>}
      <button type="button" className="primary" disabled={state.stage !== 'ready'} onClick={() => flow.confirm()}>{state.stage === 'confirming' ? 'Recording visit…' : state.stage === 'confirmed' ? 'Visit confirmed' : 'Confirm visit'}</button>
      <button type="button" className="secondary" disabled={busy} onClick={() => { setToken(''); setQuery(''); flow.clear() }}>Clear / change customer</button>
      {state.stage === 'confirmed' && <button type="button" className="secondary" onClick={() => { setToken(''); setQuery(''); flow.clear() }}>Scan next customer</button>}
    </div>}
  </section>
}
