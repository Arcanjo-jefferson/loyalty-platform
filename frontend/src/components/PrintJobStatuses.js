import { createElement as h } from 'react'
import { ticketNames, printStatus } from '../printFlow.js'

export default function PrintJobStatuses({ jobs, onInspect, busy = false }) {
  if (!jobs) return null
  if (!jobs.length) return h('p', null, 'No print jobs. Historical visits are not queued automatically.')
  return h('ul', { className: 'print-job-list', 'aria-label': 'Ticket print status' }, ...jobs.map(job =>
    h('li', { key: job.print_job_id }, h('span', null, `${job.reprint_of ? 'REPRINT · ' : ''}${ticketNames[job.ticket_type] || 'Ticket'} — ${printStatus(job)}`),
      onInspect && h('button', { className: 'secondary', type: 'button', disabled: busy, onClick: () => onInspect(job.print_job_id) }, 'Review ticket'))))
}
