import { createElement as h } from 'react'

export default function CustomerRaffleView({ state, onRefresh }) {
  return h('section', { className: 'panel customer-raffle', 'aria-label': 'Daily Raffle history' },
    h('h2', null, 'Daily Raffle'),
    h('p', null, 'Recent entries from confirmed visits. Historical visits before Daily Raffle was introduced are not included.'),
    h('button', { type: 'button', className: 'secondary', disabled: state.busy, onClick: onRefresh }, 'Refresh raffle history'),
    state.error && h('p', { role: 'alert', className: 'notification notification--error' }, state.error),
    state.busy && h('p', { role: 'status' }, 'Loading raffle history…'),
    state.entries && (state.entries.length
      ? h('ol', null, ...state.entries.slice(0, 10).map(entry => h('li', { key: entry.raffle_entry_id },
        `${entry.raffle_date} · Visit ${entry.visit_number} · ${new Date(entry.created_at).toLocaleString('en-IE', { timeZone: 'Europe/Dublin' })} (Europe/Dublin)`)))
      : h('p', null, 'No Daily Raffle entries yet.')))
}
