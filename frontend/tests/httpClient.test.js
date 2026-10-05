import test from 'node:test'
import assert from 'node:assert/strict'
import { createAuthenticatedClient } from '../src/httpClient.js'
const response = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body })

test('attaches fresh bearer token and preserves save payload without adding a tenant', async () => {
  const client = createAuthenticatedClient({ base: 'http://test.invalid', getToken: async () => 'fixture-token', onExpired: () => assert.fail(), fetchRequest: async (url, options) => {
    assert.equal(url, 'http://test.invalid/customers')
    assert.equal(options.headers.Authorization, 'Bearer fixture-token')
    assert.equal(options.body, '{"first_name":"Fictional"}')
    return response(201, { customer_id: 'fixture' })
  } })
  assert.deepEqual(await client('/customers', { method: 'POST', body: '{"first_name":"Fictional"}' }), { customer_id: 'fixture' })
})

test('refreshes once on 401 and retries the request', async () => {
  const refreshes = [], calls = []
  const client = createAuthenticatedClient({ base: '', getToken: async force => { refreshes.push(force); return force ? 'refreshed' : 'initial' }, onExpired: () => assert.fail(), fetchRequest: async (_, options) => { calls.push(options.headers.Authorization); return calls.length === 1 ? response(401, {}) : response(200, []) } })
  assert.deepEqual(await client('/customers'), [])
  assert.deepEqual(refreshes, [undefined, true])
  assert.deepEqual(calls, ['Bearer initial', 'Bearer refreshed'])
})

test('missing token or failed refresh expires session; never sends an anonymous request', async () => {
  let expired = 0, calls = 0
  const client = createAuthenticatedClient({ base: '', getToken: async () => { throw new Error('test') }, onExpired: () => expired++, fetchRequest: async () => { calls++; return response(200, {}) } })
  await assert.rejects(client('/customers'), /session has expired/)
  assert.equal(expired, 1); assert.equal(calls, 0)
})

test('repeated unauthorized response expires session after one retry', async () => {
  let expired = 0, calls = 0
  const client = createAuthenticatedClient({ base: '', getToken: async () => 'fixture', onExpired: () => expired++, fetchRequest: async () => { calls++; return response(401, {}) } })
  await assert.rejects(client('/customers'), /session has expired/)
  assert.equal(calls, 2); assert.equal(expired, 1)
})

test('403 stays an authorization error without logging out or retrying', async () => {
  let calls = 0
  const client = createAuthenticatedClient({ base: '', getToken: async () => 'fixture', onExpired: () => assert.fail(), fetchRequest: async () => { calls++; return response(403, { detail: 'Permission denied.' }) } })
  await assert.rejects(client('/customers'), /Permission denied/)
  assert.equal(calls, 1)
})
