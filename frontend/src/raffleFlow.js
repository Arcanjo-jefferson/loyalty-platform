import { rewardMessages } from './voucherFlow.js'

export function visitSuccessMessages(result) {
  return ['Visit recorded successfully.',
    ...(result.raffle_entry ? ['Daily Raffle entry created.'] : []),
    ...rewardMessages(result.vouchers)]
}

export function createRaffleHistory({ request }) {
  let state = { entries: null, busy: false, error: '' }
  let generation = 0
  const listeners = new Set()
  const publish = value => { state = value; listeners.forEach(listener => listener()) }
  return {
    getSnapshot: () => state,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    cancel() { generation++; state = { entries: null, busy: false, error: '' } },
    async load(customerId) {
      const attempt = ++generation
      publish({ entries: null, busy: true, error: '' })
      try {
        const entries = await request(`/customers/${encodeURIComponent(customerId)}/raffle-entries`, { cache: 'no-store' })
        if (generation === attempt) publish({ entries, busy: false, error: '' })
      } catch (error) {
        if (generation === attempt) publish({ entries: null, busy: false, error: error.message === 'Failed to fetch' ? 'Cannot load Daily Raffle history. Please try again.' : error.message })
      }
    },
  }
}
