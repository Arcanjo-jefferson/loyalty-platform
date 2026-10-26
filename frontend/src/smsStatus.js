// Human-readable labels; only a verified DELIVERED status may claim delivery.
export const pendingSMS = campaign => campaign?.recipients?.some(r => ['QUEUED', 'SUBMITTING', 'RETRYABLE'].includes(r.status))
export function smsStatusLabel(status, reason) {
  if (status === 'SUPPRESSED' && reason === 'BUDGET_MONTH_CLOSED') return 'Not sent — monthly sending period ended'
  return ({ QUEUED: 'Queued', SUBMITTING: 'Processing', RETRYABLE: 'Waiting to process',
    SIMULATED: 'Simulation complete — no real SMS sent', UNKNOWN: 'Delivery unknown — needs review',
    SUPPRESSED: 'Not sent — customer is no longer eligible', FAILED: 'Failed — message could not be sent',
    SENT: 'Sent — delivery not confirmed', ACCEPTED: 'Queued — accepted by provider; delivery not confirmed', DELIVERED: 'Delivered',
    UNDELIVERED: 'Failed — message could not be delivered' })[status] || 'Status unavailable'
}
export function campaignOutcome(campaign) {
  const rows = campaign?.recipients || []
  if (!rows.length) return { message: 'No messages were sent.', variant: 'error' }
  if (rows.some(r => r.status === 'UNKNOWN')) return { message: 'Some message outcomes are unknown and need review. They will not be sent again automatically.', variant: 'error' }
  if (pendingSMS(campaign)) return { message: 'Your messages are queued for simulation. No real SMS has been sent.', variant: 'success' }
  if (rows.every(r => r.status === 'SIMULATED')) return { message: 'Simulation completed successfully. No real SMS was sent.', variant: 'success' }
  if (rows.every(r => r.status === 'DELIVERED')) return { message: 'Your messages were delivered.', variant: 'success' }
  if (rows.every(r => ['SUPPRESSED', 'FAILED', 'UNDELIVERED'].includes(r.status))) return { message: 'The messages could not be sent. See message history for details.', variant: 'error' }
  return { message: 'Processing finished. See message history for each customer’s result.', variant: 'success' }
}
