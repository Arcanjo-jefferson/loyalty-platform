import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { createPrintFlow, printStatus } from '../src/printFlow.js'
import PrintJobStatuses from '../src/components/PrintJobStatuses.js'
import { createVisitFlow } from '../src/visitFlow.js'

const job = { print_job_id: 'fixture.print.DAILY_RAFFLE', customer_id: 'fixture', source_visit_id: 'print', ticket_type: 'DAILY_RAFFLE', status: 'PENDING', display_status: 'Queued' }
const ticket = { template_version: 3, issued_at: '2026-10-08T12:45:00Z', receipt_text: 'Trumps\nLOYALTY BONUS\nFictional Customer\n+353831234567\nIssued date: 08/10/2026\nIssued time: 13:45\nEurope/Dublin' }
const detail = { ...job, status: 'UNCERTAIN', ticket }

test('new visit jobs show Queued for raffle and vouchers, never Printed', async () => {
  const jobs = [job, { ...job, print_job_id: 'loyalty', ticket_type: 'LOYALTY_10' }, { ...job, print_job_id: 'birthday', ticket_type: 'BIRTHDAY_20' }]
  const html = renderToStaticMarkup(createElement(PrintJobStatuses, { jobs }))
  assert.equal((html.match(/Queued/g) || []).length, 3)
  assert.match(html, /Daily Raffle ticket/); assert.match(html, /€10 Loyalty Voucher ticket/); assert.match(html, /€20 Birthday Voucher ticket/)
  assert.doesNotMatch(html, /Printed|fixture.print|voucher_code|claim_token/)
  const customer = { customer_id: 'fixture' }
  const flow = createVisitFlow({ request: async (path, options) => options.method === 'POST' && path.endsWith('/visits')
    ? { customer, progress: 1, raffle_entry: {}, print_jobs: jobs } : { customer, progress: 0 } })
  await flow.lookup('fictional-qr-token-123'); await flow.confirm()
  assert.deepEqual(flow.getSnapshot().result.print_jobs, jobs)
  assert.match(flow.getSnapshot().notice, /Daily Raffle entry created/)
  assert.doesNotMatch(flow.getSnapshot().notice, /Printed/)
})

test('queue statuses distinguish completed, retryable, uncertain and clearly labelled reprints', () => {
  for (const [status, label] of [['PENDING', 'Queued'], ['COMPLETED', 'Printed'], ['UNCERTAIN', 'Uncertain — operator review required'], ['FAILED', 'Failed'], ['RETRYABLE', 'Retryable']]) assert.equal(printStatus({ status }), label)
  const html = renderToStaticMarkup(createElement(PrintJobStatuses, { jobs: [{ ...job, reprint_of: 'original', status: 'UNCERTAIN' }], onInspect: () => {} }))
  assert.match(html, /REPRINT/); assert.match(html, /operator review required/); assert.match(html, /Review ticket/)
})

test('customer summaries and management review use authenticated API boundaries with no writes on viewing', async () => {
  const calls = []
  const flow = createPrintFlow({ request: async (path, options) => { calls.push([path, options]); return path.includes('/fixture.print') ? detail : [job] } })
  await flow.load('fixture'); assert.equal(calls[0][0], '/customers/fixture/print-jobs')
  await flow.load(null, true); assert.equal(calls[1][0], '/print-jobs?review=true')
  await flow.inspect(job.print_job_id); assert.deepEqual(flow.getSnapshot().detail, detail)
  assert.ok(calls.every(([, options]) => !options.method && !options.body))
})

test('explicit reprints require confirmation/reason, retain idempotent request on failure and claim no physical success', async () => {
  const calls = []; let fail = true; let generated = 0
  const flow = createPrintFlow({ newId: () => { generated++; return 'request-fixture' }, request: async (path, options) => {
    calls.push([path, JSON.parse(options.body)])
    if (fail) throw Error('Connection lost; inspect queue before retrying')
    return { ...job, print_job_id: 'reprint', reprint_of: job.print_job_id }
  } })
  await flow.reprint(job.print_job_id, 'Paper damaged', false)
  await flow.reprint(job.print_job_id, 'a', true); assert.equal(calls.length, 0)
  await flow.reprint(job.print_job_id, 'Paper damaged', true)
  assert.equal(flow.getSnapshot().notice, ''); assert.match(flow.getSnapshot().error, /Connection lost/)
  fail = false; await flow.reprint(job.print_job_id, 'Paper damaged', true)
  assert.equal(generated, 1); assert.deepEqual(calls[0], calls[1])
  assert.deepEqual(calls[1][1], { request_id: 'request-fixture', reason: 'Paper damaged', confirmed: true })
  assert.match(flow.getSnapshot().notice, /Reprint queued.*No new reward/)
  assert.doesNotMatch(flow.getSnapshot().notice, /Printed/)
})

test('error, unmount and expired-lease review never queue another job automatically', async () => {
  let release
  const late = createPrintFlow({ request: () => new Promise(resolve => { release = resolve }) })
  const pending = late.load('fixture'); late.cancel(); release([job]); await pending
  assert.equal(late.getSnapshot().jobs, null)
  const calls = []
  const flow = createPrintFlow({ request: async (path, options) => { calls.push([path, options]); return detail } })
  await flow.review(job.print_job_id)
  assert.equal(calls.length, 1); assert.match(calls[0][0], /\/review$/)
  assert.match(flow.getSnapshot().notice, /No ticket was printed/)
  assert.equal(flow.getSnapshot().detail.status, 'UNCERTAIN')
})

test('actual app/profile/scanner render paths enforce manager-only admin, immutable preview and no browser printing', () => {
  const source = path => readFileSync(new URL(path, import.meta.url), 'utf8')
  const view = source('../src/components/PrintJobs.jsx')
  assert.match(view, /\['OWNER', 'MANAGER'\].includes\(user.role\)/)
  assert.match(view, /!customerId && !canManage/)
  assert.match(view, /onInspect=\{canManage/)
  assert.match(view, /detail.ticket.receipt_text/)
  assert.match(view, /confirmed.*reason.trim\(\).length/)
  assert.match(view, /additional ticket marked REPRINT/)
  assert.match(source('../src/components/VisitScanner.jsx'), /<PrintJobStatuses jobs=\{result.print_jobs\}/)
  assert.match(source('../src/components/CustomerProfile.jsx'), /<PrintJobs/)
  assert.match(source('../src/App.jsx'), /print-queue.*Print queue/)
  for (const path of ['../src/components/PrintJobs.jsx', '../src/printFlow.js']) assert.doesNotMatch(source(path), /window.print\(|\/claim|\/start|\/complete/)
})


test('actual attention checkbox keeps review filter and uses the requested friendly label', async () => {
  const source = readFileSync(new URL('../src/components/PrintJobs.jsx', import.meta.url), 'utf8')
  assert.ok(source.includes('Show only jobs that need attention'))
  assert.ok(source.includes('flow.load(customerId, reviewOnly)'))
  assert.ok(!source.includes('Failed, uncertain or retryable jobs only'))
})


test('ticket preview retains original issuance display through review and explicit reprint', async () => {
  const flow = createPrintFlow({ newId: () => 'request', request: async (path, options) => options.method
    ? { ...detail, print_job_id: 'reprint', reprint_of: job.print_job_id, ticket: { ...ticket, receipt_text: 'REPRINT\n' + ticket.receipt_text } }
    : detail })
  await flow.inspect(job.print_job_id)
  assert.equal(flow.getSnapshot().detail.ticket.issued_at, ticket.issued_at)
  assert.match(flow.getSnapshot().detail.ticket.receipt_text, /Issued date: 08\/10\/2026\nIssued time: 13:45/)
  await flow.reprint(job.print_job_id, 'Paper damaged', true)
  const snapshot = flow.getSnapshot().jobs[0].ticket
  assert.equal(snapshot.issued_at, ticket.issued_at)
  assert.equal(snapshot.receipt_text, 'REPRINT\n' + ticket.receipt_text)
})
