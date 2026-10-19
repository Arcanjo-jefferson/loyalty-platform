import { campaignOutcome } from './smsStatus.js'
export const canUseSMS = role => ['OWNER', 'MANAGER'].includes(role)
export const smsMoney = micros => new Intl.NumberFormat('en-IE', { style: 'currency', currency: 'EUR', maximumFractionDigits: 4 }).format(micros / 1000000)
export const exampleSMS = 'TRUMPS PLAZA\n\nHi {first_name}, we have something special for you! Visit us soon.\n\nReply STOP to opt out.'

export function createSMSFlow({ role, request }) {
  let state = { busy: false, settings: null, history: [], preview: null, error: '', notice: '', searchQuery: '', searchResults: [], searchTotal: 0, searchLoading: false, searchError: '', selectedCustomer: null, metadataLoading: false, metadataError: '', stage: 'compose', result: null, statusError: '' }
  let generation = 0; let searchGeneration = 0; let metadataGeneration = 0
  const listeners = new Set()
  const publish = change => { state = { ...state, ...change }; listeners.forEach(fn => fn()) }
  const post = (path, data) => request(path, { method: 'POST', body: JSON.stringify(data), cache: 'no-store' })
  function allowed() {
    if (canUseSMS(role)) return true
    publish({ error: 'Only Owner and Manager may use SMS Messaging.' }); return false
  }
  async function operation(work) {
    if (!allowed() || state.busy) return false
    const attempt = ++generation
    publish({ busy: true, error: '', notice: '' })
    try {
      const result = await work()
      if (generation === attempt) { publish({ ...result, busy: false }); return true }
    } catch (error) { if (generation === attempt) publish({ busy: false, error: error.message === 'Failed to fetch' ? 'Unable to confirm the result. If you already confirmed, check message history before starting a new message.' : error.message, notice: '' }) }
    return false
  }
  const flow = {
    getSnapshot: () => state,
    subscribe(fn) { listeners.add(fn); return () => listeners.delete(fn) },
    cancel() { generation++; searchGeneration++; metadataGeneration++; state = { ...state, busy: false, preview: null, history: [], settings: null, selectedCustomer: null, searchResults: [], searchLoading: false } },
    invalidate() { generation++; publish({ preview: null, error: '', notice: '', busy: false, stage: 'compose', result: null }) },
    reset() { generation++; searchGeneration++; metadataGeneration++; publish({ stage: 'compose', result: null, preview: null, selectedCustomer: null, searchQuery: '', searchResults: [], searchTotal: 0, searchLoading: false, searchError: '', error: '', notice: '', statusError: '', busy: false }) },
    goBack() { if (!state.busy) publish({ stage: 'compose', error: '', notice: '' }) },
    async review(values) {
      if (!allowed() || state.busy) return false
      const ok = state.preview ? true : await flow.preview(values)
      if (!ok) return false
      if (!state.preview.recipient_count) { publish({ preview: null, error: 'No eligible customers were found. Choose another customer or check marketing consent.' }); return false }
      publish({ stage: 'confirm', error: '', notice: '' }); return true
    },
    async refreshResult() {
      if (!allowed() || !state.result) return false
      const identity = state.result.campaign_id
      try {
        const result = await request(`/sms/campaigns/${encodeURIComponent(identity)}`, { cache: 'no-store' })
        if (state.result?.campaign_id !== identity) return false
        publish({ result, statusError: '', notice: campaignOutcome(result).message, history: [result, ...state.history.filter(c => c.campaign_id !== identity)] }); return true
      } catch {
        if (state.result?.campaign_id === identity) publish({ statusError: 'Unable to update the result right now. Your queued message has not been submitted again.' })
        return false
      }
    },
    async load() {
      if (!allowed() || state.busy) return false
      const attempt = ++metadataGeneration; const actionVersion = generation
      publish({ metadataLoading: true, metadataError: '' })
      const [settings, history] = await Promise.allSettled([
        request('/sms/settings', { cache: 'no-store' }), request('/sms/history', { cache: 'no-store' }),
      ])
      if (attempt !== metadataGeneration) return false
      // A slow refresh cannot replace the outcome of a newer confirmation/action.
      const update = actionVersion === generation ? {
        ...(settings.status === 'fulfilled' ? { settings: settings.value } : {}),
        ...(history.status === 'fulfilled' ? { history: history.value } : {}),
      } : {}
      const errors = [settings, history].filter(r => r.status === 'rejected').map(r => r.reason.message)
      publish({ ...update, metadataLoading: false, metadataError: errors.join(' ') })
      return errors.length === 0
    },
    prepareSearch(query) {
      if (!allowed()) return
      searchGeneration++
      publish({ searchQuery: query, searchResults: [], searchTotal: 0, searchError: '', searchLoading: Boolean(query.trim()) })
    },
    async searchCustomers(query) {
      if (!allowed()) return false
      const attempt = ++searchGeneration
      publish({ searchQuery: query, searchResults: [], searchTotal: 0, searchError: '', searchLoading: Boolean(query.trim()) })
      if (!query.trim()) return true
      try {
        const result = await request(`/sms/customers?q=${encodeURIComponent(query.trim())}`, { cache: 'no-store' })
        if (attempt !== searchGeneration) return false
        const updatedSelection = result.results.find(c => c.customer_id === state.selectedCustomer?.customer_id)
        publish({ searchResults: result.results, searchTotal: result.total_matches, searchLoading: false,
          ...(updatedSelection ? { selectedCustomer: updatedSelection, ...(!updatedSelection.sms_eligible ? { preview: null } : {}) } : {}) })
        return true
      } catch (error) {
        if (attempt === searchGeneration) publish({ searchLoading: false, searchError: error.message === 'Failed to fetch' ? 'Unable to search customers. Check the connection and try again.' : error.message })
        return false
      }
    },
    selectCustomer(id) {
      if (!allowed() || state.busy) return false
      const customer = state.searchResults.find(c => c.customer_id === id)
      if (!customer?.sms_eligible) return false
      generation++; publish({ selectedCustomer: customer, preview: null, notice: '', error: '' })
      return true
    },
    clearSelection() {
      generation++; searchGeneration++
      publish({ selectedCustomer: null, preview: null, searchQuery: '', searchResults: [], searchTotal: 0, searchError: '', searchLoading: false })
    },
    preview(values) {
      if (values.audience === 'individual' && (!state.selectedCustomer?.sms_eligible || values.customer_id !== state.selectedCustomer.customer_id)) {
        publish({ error: 'Select an eligible customer from the search results.', preview: null }); return Promise.resolve(false)
      }
      return operation(async () => ({ preview: await post('/sms/preview', {
      audience: values.audience, ...(values.audience === 'individual' ? { customer_id: values.customer_id } : {}), message: values.message,
    }) })) },
    confirm(confirmed) {
      if (!allowed() || !confirmed || !state.preview || state.preview.recipient_count === 0 || state.preview.status !== 'DRAFT') return Promise.resolve(false)
      const preview = state.preview
      return operation(async () => {
        let campaign
        try { campaign = await post(`/sms/campaigns/${encodeURIComponent(preview.campaign_id)}/confirm`, { confirmed: true }) }
        catch (error) {
          if ([409, 422].includes(error.status)) publish({ stage: 'compose', preview: null })
          throw error
        }
        // Show canonical committed result immediately, including after a lost earlier response.
        return { stage: 'result', result: campaign, statusError: '', preview: null, history: [campaign, ...state.history.filter(c => c.campaign_id !== campaign.campaign_id)],
          notice: campaignOutcome(campaign).message }
      })
    },
    simulate() { return operation(async () => {
      await post('/sms/simulate', {})
      const [history, settings] = await Promise.all([request('/sms/history', { cache: 'no-store' }), request('/sms/settings', { cache: 'no-store' })])
      return { history, settings, notice: 'Simulation completed. Review message statuses; no real SMS was sent.' }
    }) },
    suppress(customerId, confirmed) {
      if (!allowed() || !confirmed) return Promise.resolve(false)
      return operation(async () => {
        await post(`/sms/customers/${encodeURIComponent(customerId)}/suppress`, { confirmed: true })
        return { preview: null, selectedCustomer: state.selectedCustomer?.customer_id === customerId ? { ...state.selectedCustomer, sms_eligible: false, ineligible_reason: 'Customer has opted out of SMS.' } : state.selectedCustomer,
          searchResults: state.searchResults.map(c => c.customer_id === customerId ? { ...c, sms_eligible: false, ineligible_reason: 'Customer has opted out of SMS.' } : c), notice: 'SMS opt-out recorded. This phone is excluded from future simulated sends.' }
      })
    },
  }
  return flow
}

// Compose-only example. The server generates the final personalised preview on Send.
export function composeSMSPreview(values, customer) {
  if (values.audience === 'individual' && !customer) return null
  const sample = values.audience === 'all'
  const firstName = sample ? 'Sarah' : customer.first_name || customer.name.split(/\s+/)[0]
  const body = values.message.replaceAll('{first_name}', firstName)
  return { campaign_id: 'compose', sender: 'Your business', recipients: [{ id: sample ? 'example' : customer.customer_id,
    name: sample ? 'Sarah (example)' : customer.name, phone: sample ? '' : customer.masked_phone, body }] }
}
