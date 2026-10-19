import { useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { apiRequest } from '../api'
import { useAuth } from '../AuthContext'
import { canUseSMS, composeSMSPreview, createSMSFlow, exampleSMS } from '../smsFlow'
import { campaignOutcome, pendingSMS } from '../smsStatus'
import Notification from './Notification'
import SMSPreview from './SMSPreview'
import SMSConfirmation from './SMSConfirmation'
import SMSHistory from './SMSHistory'
import SMSAudienceCards from './SMSAudienceCards'
import SMSCustomerResults from './SMSCustomerResults'

export default function SMSMessaging() {
  const { user } = useAuth()
  if (!canUseSMS(user.role)) return <section className="panel sms-panel" role="alert">Only Owner and Manager may use SMS Messaging.</section>
  return <SMSWorkspace key={`${user.business_id}:${user.subject}`} role={user.role} business={user.business_id} />
}

function SMSWorkspace({ role, business }) {
  const [flow] = useState(() => createSMSFlow({ role, request: apiRequest }))
  const state = useSyncExternalStore(flow.subscribe, flow.getSnapshot)
  const initial = () => ({ audience: 'individual', customer_id: '', message: business === 'trumps' ? exampleSMS : 'Hi {first_name}, visit us soon.\n\nReply STOP to opt out.' })
  const [values, setValues] = useState(initial)
  const [search, setSearch] = useState('')
  const [historyOpen, setHistoryOpen] = useState(false)
  const heading = useRef(null)
  useEffect(() => () => flow.cancel(), [flow])
  useEffect(() => { heading.current?.focus() }, [state.stage])
  useEffect(() => {
    if (values.audience !== 'individual' || state.stage !== 'compose') return
    const timer = setTimeout(() => flow.searchCustomers(search), 250)
    return () => clearTimeout(timer)
  }, [flow, search, values.audience, state.stage])
  useEffect(() => {
    if (state.stage !== 'result' || !pendingSMS(state.result)) return
    const timer = setTimeout(() => flow.refreshResult(), 2000)
    return () => clearTimeout(timer)
  }, [flow, state.stage, state.result, state.statusError])
  function edit(change) { setValues(old => ({ ...old, ...change })); flow.invalidate() }
  function changeAudience(audience) { setSearch(''); flow.clearSelection(); edit({ audience, customer_id: '' }) }
  function selectCustomer(id) { if (flow.selectCustomer(id)) setValues(old => ({ ...old, customer_id: id })) }
  function newMessage() { flow.reset(); setSearch(''); setValues(initial()) }
  const outcome = state.result ? campaignOutcome(state.result) : null
  return <div className="sms-workspace">
    <section className="panel sms-panel">
      <h2 ref={heading} tabIndex={-1}>{state.stage === 'confirm' ? 'Confirm your message' : state.stage === 'result' ? 'Message result' : 'Write a message'}</h2>
      <p className="sms-simulation">Test mode is on. No real text messages will be sent.</p>
      <Notification message={state.error} variant="error" />
      {state.stage === 'compose' && <form onSubmit={event => { event.preventDefault(); flow.review(values) }}>
        <fieldset disabled={state.busy}>
          <legend className="sr-only">Choose customers and write your message</legend>
          <SMSAudienceCards value={values.audience} onChange={changeAudience} disabled={state.busy} />
          {values.audience === 'individual' && <>
            <label htmlFor="sms-customer-query">Find customer</label>
            <input id="sms-customer-query" type="search" maxLength={100} value={search} placeholder="Name or Irish phone number" autoComplete="off"
              onChange={e => { setSearch(e.target.value); flow.prepareSearch(e.target.value) }}
              onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); flow.searchCustomers(search) } }} />
            <SMSCustomerResults query={state.searchQuery} results={state.searchResults} total={state.searchTotal}
              loading={state.searchLoading} error={state.searchError} selected={state.selectedCustomer}
              onSelect={selectCustomer} onRetry={() => flow.searchCustomers(search)} disabled={state.busy} />
            {state.selectedCustomer && <section className="sms-selected-customer" aria-label="Selected customer">
              <strong>Selected: {state.selectedCustomer.name}</strong><span>{state.selectedCustomer.masked_phone}</span>
              {!state.selectedCustomer.sms_eligible && <span>{state.selectedCustomer.ineligible_reason}</span>}
            </section>}
          </>}
          <label>Message<textarea rows="7" required maxLength={1600} value={values.message} onChange={e => edit({ message: e.target.value })} /></label>
          <small>Use {'{first_name}'} to include each customer’s first name.</small>
        </fieldset>
        <SMSPreview preview={composeSMSPreview(values, state.selectedCustomer)} sample={values.audience === 'all'} />
        <p className="muted">You can review the final message and cost before confirming.</p>
        <div className="sms-compose-actions">
          <button className="primary" type="submit" disabled={state.busy || !values.message.trim() || values.audience === 'individual' && !state.selectedCustomer?.sms_eligible}>{state.busy ? 'Please wait…' : 'Send message'}</button>
          <button className="secondary" type="button" onClick={newMessage}>Cancel</button>
        </div>
      </form>}
      {state.stage === 'confirm' && state.preview && <SMSConfirmation preview={state.preview} busy={state.busy}
        onConfirm={() => flow.confirm(true)} onBack={() => flow.goBack()} />}
      {state.stage === 'result' && outcome && <section aria-label="Sending result" className="sms-result">
        <Notification message={outcome.message} variant={outcome.variant} />
        {state.statusError && <p role="status">{state.statusError}</p>}
        <button type="button" className="primary" onClick={newMessage}>Start a new message</button>
      </section>}
    </section>
    <details className="panel sms-panel sms-history-section" open={historyOpen} onToggle={event => {
      const open = event.currentTarget.open
      if (open !== historyOpen) { setHistoryOpen(open); if (open) flow.load() }
    }}>
      <summary>Message history</summary>
      {historyOpen && <>
        {state.metadataLoading && <p role="status">Loading messages…</p>}
        <Notification message={state.metadataError} variant="error" />
        <SMSHistory history={state.history} />
      </>}
    </details>
  </div>
}
