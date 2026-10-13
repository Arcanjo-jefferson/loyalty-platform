import { useEffect, useState, useSyncExternalStore } from 'react'
import { useAuth } from '../AuthContext'
import { apiRequest } from '../api'
import { createPrintDevicesFlow } from '../printDevicesFlow'
import PrintDeviceList from './PrintDeviceList.js'
import Notification from './Notification'

export default function PrintDevices() {
  const { user } = useAuth()
  if (user.role !== 'OWNER') return <p role="alert">Only Owner users may manage print devices.</p>
  return <OwnerPrintDevices key={`${user.business_id}:${user.subject || ''}`} />
}

function OwnerPrintDevices() {
  const [flow] = useState(() => createPrintDevicesFlow({ request: apiRequest, role: 'OWNER' }))
  const state = useSyncExternalStore(flow.subscribe, flow.getSnapshot)
  const [label, setLabel] = useState('')
  const [pending, setPending] = useState(null)
  const [confirmed, setConfirmed] = useState(false)
  useEffect(() => { flow.load(); return () => flow.cancel() }, [flow])
  const clearAction = () => { setPending(null); setConfirmed(false) }
  return <section className="panel print-devices">
    <h2>Print devices</h2>
    <p>Register and manage devices for your business. Registration and rotation require separate provisioning before a device can connect.</p>
    <Notification message={state.error} variant="error" /><Notification message={state.notice} />
    <form className="device-registration" onSubmit={async event => { event.preventDefault(); if (await flow.register(label)) setLabel('') }}>
      <label htmlFor="device-label">Device label<input id="device-label" value={label} maxLength={80} required disabled={state.busy} placeholder="For example, Front desk Windows PC" onChange={event => setLabel(event.target.value)} /></label>
      <button type="submit" className="primary" disabled={state.busy || !label.trim()}>Register Device</button>
    </form>
    {state.registered && <div className="device-registration-result" role="status"><strong>{state.registered.label}</strong><p>Device ID: <span className="device-id">{state.registered.device_id}</span></p><p>Status: {state.registered.status}</p></div>}
    <div className="device-section-heading"><h3>Registered devices</h3><button type="button" className="secondary" disabled={state.busy} onClick={() => { clearAction(); flow.load() }}>Refresh devices</button></div>
    {state.busy && <p role="status">Updating device information…</p>}
    <PrintDeviceList devices={state.devices} busy={state.busy} onAction={(device, action) => { setPending({ device, action }); setConfirmed(false) }} />
    {pending && <div className="device-confirmation" role="region" aria-label="Confirm device action">
      <h3>{pending.action === 'disable' ? 'Disable device?' : 'Request credential rotation?'}</h3>
      <p><strong>{pending.device.label}</strong> · <span className="device-id">{pending.device.device_id}</span></p>
      <p>{pending.action === 'disable' ? 'This device will no longer be authorized to connect. An already submitted print cannot be recalled.' : 'The device will stop connecting until new credentials are provisioned. This request does not create provider credentials.'}</p>
      <label className="print-checkbox"><input type="checkbox" checked={confirmed} disabled={state.busy} onChange={event => setConfirmed(event.target.checked)} />I confirm this device action.</label>
      <div className="device-actions"><button type="button" className="primary" disabled={state.busy || !confirmed} onClick={async () => { if (await flow.action(pending.device.device_id, pending.action, confirmed)) clearAction() }}>{pending.action === 'disable' ? 'Confirm disable' : 'Confirm rotation request'}</button><button type="button" className="secondary" disabled={state.busy} onClick={clearAction}>Cancel</button></div>
    </div>}
  </section>
}
