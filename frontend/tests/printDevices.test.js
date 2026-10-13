import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { readFileSync } from 'node:fs'
import { createPrintDevicesFlow } from '../src/printDevicesFlow.js'
import PrintDeviceList from '../src/components/PrintDeviceList.js'
const device = { device_id: 'fictional-device', label: 'Front desk', status: 'ACTIVE', last_seen: '2026-10-08T12:00:00Z' }

test('Owner lookup is read-only and displays only safe metadata', async () => {
  const calls = []
  const flow = createPrintDevicesFlow({ role: 'OWNER', request: async (...args) => { calls.push(args); return [{ ...device, client_secret: 'never-render', access_token: 'never-render' }] } })
  await flow.load()
  assert.deepEqual(calls, [['/print-devices', { cache: 'no-store' }]])
  assert.deepEqual(flow.getSnapshot().devices, [device])
  const html = renderToStaticMarkup(createElement(PrintDeviceList, { devices: flow.getSnapshot().devices, onAction: () => {} }))
  for (const text of ['Front desk', 'ACTIVE', 'fictional-device', 'Last seen']) assert.ok(html.includes(text))
  assert.doesNotMatch(html, /never-render/)
})

test('registration sends only trimmed label and shows returned pending device immediately', async () => {
  const pending = { ...device, status: 'PENDING_PROVISIONING', last_seen: null }; const calls = []
  const flow = createPrintDevicesFlow({ role: 'OWNER', request: async (...args) => { calls.push(args); return pending } })
  assert.equal(await flow.register('  Front desk  '), true)
  assert.equal(calls[0][0], '/print-devices'); assert.equal(calls[0][1].method, 'POST')
  assert.deepEqual(JSON.parse(calls[0][1].body), { label: 'Front desk' })
  assert.deepEqual(flow.getSnapshot().registered, pending)
  assert.deepEqual(flow.getSnapshot().devices, [pending])
})

test('Manager and Staff cannot perform any device UI requests', async () => {
  for (const role of ['MANAGER', 'STAFF']) {
    let count = 0
    const flow = createPrintDevicesFlow({ role, request: () => { count++; throw Error('Unexpected') } })
    await flow.load(); await flow.register('Device'); await flow.action(device.device_id, 'disable', true); await flow.action(device.device_id, 'rotate', true)
    assert.equal(count, 0); assert.match(flow.getSnapshot().error, /Only Owner/)
  }
})

test('disable and rotation require confirmation and show backend status', async () => {
  for (const action of ['disable', 'rotate']) {
    const calls = []; const updated = { ...device, status: action === 'disable' ? 'DISABLED' : 'PENDING_PROVISIONING' }
    const flow = createPrintDevicesFlow({ role: 'OWNER', request: async (path, options) => { calls.push([path, options]); return options.method ? updated : [device] } })
    await flow.load()
    assert.equal(await flow.action(device.device_id, action, false), false); assert.equal(calls.length, 1)
    assert.equal(await flow.action(device.device_id, action, true), true)
    assert.equal(calls[1][0], `/print-devices/${device.device_id}/${action}`); assert.equal(calls[1][1].body, '{}')
    assert.deepEqual(flow.getSnapshot().devices, [updated])
    assert.match(flow.getSnapshot().notice, action === 'disable' ? /disabled/ : /rotation requested/)
  }
})

test('invalid labels and failed writes cannot show success or invent status', async () => {
  const flow = createPrintDevicesFlow({ role: 'OWNER', request: async (path, options) => { if (!options.method) return [device]; throw Error('Not authorized') } })
  for (const label of ['', '   ', 'x'.repeat(81), 'line\nbreak']) assert.equal(await flow.register(label), false)
  await flow.load(); assert.equal(await flow.register('Desk'), false)
  assert.equal(flow.getSnapshot().registered, null); assert.equal(flow.getSnapshot().notice, '')
  assert.equal(await flow.action(device.device_id, 'disable', true), false)
  assert.deepEqual(flow.getSnapshot().devices, [device]); assert.equal(flow.getSnapshot().notice, '')
  assert.equal(flow.getSnapshot().error, 'Not authorized')
})

test('double submission and unmount prevent duplicate requests and stale results', async () => {
  let resolve; let count = 0
  const flow = createPrintDevicesFlow({ role: 'OWNER', request: () => { count++; return new Promise(done => { resolve = done }) } })
  const pending = flow.register('Desk')
  assert.equal(await flow.register('Desk'), false); assert.equal(count, 1)
  flow.cancel(); resolve(device); assert.equal(await pending, false); assert.equal(flow.getSnapshot().registered, null)
})

test('empty list, never-seen state and escaped labels render safely', () => {
  assert.match(renderToStaticMarkup(createElement(PrintDeviceList, { devices: [], onAction: () => {} })), /No print devices/)
  const html = renderToStaticMarkup(createElement(PrintDeviceList, { devices: [{ ...device, label: '<script>bad</script>', status: 'PENDING_PROVISIONING', last_seen: null }], onAction: () => {} }))
  assert.match(html, /Never seen/); assert.match(html, /&lt;script&gt;/); assert.doesNotMatch(html, /<script>/)
  assert.match(html, /disabled=""[^>]*>Request rotation/)
})

test('actual route and navigation guard Owner access and reuse authenticated transport', () => {
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
  const screen = readFileSync(new URL('../src/components/PrintDevices.jsx', import.meta.url), 'utf8')
  assert.match(app, /user.role === 'OWNER' \? \[\['print-devices'/)
  assert.match(app, /route.page === 'print-devices' && <PrintDevices/)
  assert.match(app, /'loyalty', 'vouchers', 'print-queue', 'print-devices'/)
  assert.match(screen, /if \(user.role !== 'OWNER'\) return/)
  assert.match(screen, /request: apiRequest/)
  assert.match(screen, /if \(await flow.register\(label\)\) setLabel\(''\)/)
  assert.match(screen, /disabled=\{state.busy \|\| !confirmed\}/)
  assert.match(screen, /onClick=\{clearAction\}>Cancel/)
  assert.doesNotMatch(screen, /window.confirm|alert\(|client_secret|access_token/)
})
