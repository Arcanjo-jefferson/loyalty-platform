import { createElement as h } from 'react'
import { campaignOutcome, smsStatusLabel } from '../smsStatus.js'
import { maskedPreviewPhone } from './SMSPreview.js'

const time = value => value ? new Intl.DateTimeFormat('en-IE', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Dublin' }).format(new Date(value)) : '—'
export default function SMSHistory({ history }) {
  return h('section', { className: 'sms-history-content', 'aria-label': 'Message history' },
    h('p', null, 'Simulation is on. No real SMS messages are being sent. Times: Europe/Dublin.'),
    !history.length && h('p', null, 'No messages yet.'),
    ...history.map(campaign => h('details', { key: campaign.campaign_id },
      h('summary', null, `${time(campaign.created_at)} · ${campaign.recipient_count} customer(s) · ${campaignOutcome(campaign).message}`),
      ...campaign.recipients.map(row => h('article', { key: row.id, className: 'sms-history-row' },
        h('strong', null, row.name), h('span', null, ` ${maskedPreviewPhone(row.phone)} · ${time(row.updated_at)}`),
        h('p', null, smsStatusLabel(row.status, row.reason)), h('div', { className: 'sms-body' }, row.body))))))
}
