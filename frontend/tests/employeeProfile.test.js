import test from 'node:test'
import assert from 'node:assert/strict'
import { loadEmployeeIdentity } from '../src/employeeProfile.js'

const identity = { subject: 'employee-a', business_id: 'trumps', role: 'Owner' }
const session = payload => ({ tokens: { idToken: { payload } } })
const resolve = (payload, attributes = {}) => loadEmployeeIdentity(identity, {
  fetchAuthSession: async () => session(payload), fetchUserAttributes: async () => attributes,
})
test('ID token given_name wins over name without a profile request', async () => {
  const result = await loadEmployeeIdentity(identity, {
    fetchAuthSession: async () => session({ sub: identity.subject, given_name: 'Alice', name: 'Other Person' }),
    fetchUserAttributes: async () => assert.fail('Unnecessary profile request'),
  })
  assert.deepEqual(result, { ...identity, firstName: 'Alice' })
})
test('token name uses its first word', async () => {
  assert.equal((await resolve({ sub: identity.subject, name: 'Alice Smith' })).firstName, 'Alice')
})
test('authenticated attributes supply missing token name and cannot override tenant or role', async () => {
  assert.deepEqual(await resolve({ sub: identity.subject }, { sub: identity.subject, given_name: 'Jane', name: 'Other Person', business_id: 'other', role: 'Staff' }), { ...identity, firstName: 'Jane' })
  assert.equal((await resolve({ sub: identity.subject }, { sub: identity.subject, name: 'Jane Smith' })).firstName, 'Jane')
})
test('missing, inaccessible and different employee profiles use safe fallback', async () => {
  for (const attributes of [{}, { sub: 'employee-b', given_name: 'Wrong' }, { sub: identity.subject }]) {
    assert.equal((await resolve({ sub: identity.subject }, attributes)).firstName, 'Team member')
  }
  assert.equal((await loadEmployeeIdentity(identity, {
    fetchAuthSession: async () => session({ sub: identity.subject }),
    fetchUserAttributes: async () => { throw new Error('Unavailable') },
  })).firstName, 'Team member')
  assert.equal((await resolve({ sub: 'employee-b', given_name: 'Wrong' })).firstName, 'Team member')
})
test('different employee login resolves fresh name for every role without retaining previous profile', async () => {
  for (const role of ['Owner', 'Manager', 'Staff']) {
    const next = { subject: 'employee-b', business_id: 'other-business', role }
    assert.equal((await resolve({ sub: identity.subject, given_name: 'Alice' })).firstName, 'Alice')
    assert.deepEqual(await loadEmployeeIdentity(next, {
      fetchAuthSession: async () => session({ sub: next.subject }),
      fetchUserAttributes: async () => ({ sub: next.subject, given_name: 'Bob' }),
    }), { ...next, firstName: 'Bob' })
  }
})
test('session changing during profile retrieval never displays the other employee name', async () => {
  let reads = 0
  const result = await loadEmployeeIdentity(identity, {
    fetchAuthSession: async () => session({ sub: ++reads === 1 ? identity.subject : 'employee-b' }),
    fetchUserAttributes: async () => ({ sub: identity.subject, given_name: 'Alice' }),
  })
  assert.equal(result.firstName, 'Team member')
})
