// Owner UX guard complements the authoritative backend role/tenant checks.
export function createPrintDevicesFlow({ request, role }) {
  let state = { devices: null, registered: null, busy: false, error: '', notice: '' }
  let generation = 0
  const listeners = new Set()
  const publish = updates => { state = { ...state, ...updates }; listeners.forEach(listener => listener()) }
  const allowed = () => {
    if (role === 'OWNER') return true
    publish({ error: 'Only Owner users may manage print devices.', notice: '' })
    return false
  }
  // Retain only the metadata this screen needs, never tokens/provider credentials.
  const metadata = device => ({ device_id: device.device_id, label: device.label, status: device.status, last_seen: device.last_seen })
  return {
    getSnapshot: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    cancel() { generation++; state = { devices: null, registered: null, busy: false, error: '', notice: '' } },
    async load() {
      if (!allowed() || state.busy) return
      const attempt = ++generation
      publish({ busy: true, error: '' })
      try {
        const devices = await request('/print-devices', { cache: 'no-store' })
        if (attempt === generation) publish({ devices: devices.map(metadata), busy: false })
      } catch (error) { if (attempt === generation) publish({ busy: false, error: error.message, notice: '' }) }
    },
    async register(label) {
      if (!allowed() || state.busy) return false
      label = label.trim()
      if (!label || label.length > 80 || [...label].some(character => character.charCodeAt(0) < 32 || character.charCodeAt(0) === 127)) {
        publish({ error: 'Enter a device label of 1–80 characters without control characters.', notice: '' })
        return false
      }
      const attempt = ++generation
      publish({ busy: true, error: '', notice: '', registered: null })
      try {
        const device = metadata(await request('/print-devices', { method: 'POST', body: JSON.stringify({ label }), cache: 'no-store' }))
        if (attempt === generation) {
          publish({ busy: false, registered: device, devices: [device, ...(state.devices || [])], notice: 'Device registered. Provisioning is pending.' })
          return true
        }
      } catch (error) { if (attempt === generation) publish({ busy: false, error: error.message }) }
      return false
    },
    async action(deviceId, action, confirmed) {
      if (!allowed() || state.busy) return false
      const device = state.devices?.find(item => item.device_id === deviceId)
      if (!confirmed || !device || !['disable', 'rotate'].includes(action)) {
        publish({ error: 'Select a registered device and confirm the action.', notice: '' })
        return false
      }
      const attempt = ++generation
      publish({ busy: true, error: '', notice: '' })
      try {
        const updated = metadata(await request(`/print-devices/${encodeURIComponent(deviceId)}/${action}`, { method: 'POST', body: '{}', cache: 'no-store' }))
        if (attempt === generation) {
          publish({ busy: false, devices: state.devices.map(item => item.device_id === deviceId ? updated : item),
            registered: state.registered?.device_id === deviceId ? updated : state.registered,
            notice: action === 'disable' ? 'Device disabled.' : 'Credential rotation requested. Provisioning is pending.' })
          return true
        }
      } catch (error) { if (attempt === generation) publish({ busy: false, error: error.message }) }
      return false
    },
  }
}
