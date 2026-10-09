import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createSignInFlow } from '../src/signInFlow.js'
import { withProfileName } from '../src/branding.js'

test('display enrichment runs only after authentication and backend identity, cannot alter SRP input', async () => {
  const events = []; const identity = { subject: 'verified', business_id: 'trumps', role: 'OWNER' }
  const flow = createSignInFlow({
    signIn: async input => { events.push('signIn'); assert.equal(input.username, 'Owner@example.test'); assert.equal(input.password, 'synthetic!'); return { isSignedIn: true } },
    confirmSignIn: async () => assert.fail('Not a challenge'), endSession: async () => assert.fail('No sign-out expected'),
    acceptSession: async () => {
      events.push('verifiedIdentity'); events.push('displayProfile')
      assert.deepEqual(withProfileName(identity, { sub: 'verified', given_name: 'Jane', business_id: 'other' }), { ...identity, firstName: 'Jane' })
    },
  })
  await flow.login(' Owner@example.test ', 'synthetic!')
  assert.deepEqual(events, ['signIn', 'verifiedIdentity', 'displayProfile'])
})

test('actual auth module keeps single configuration, original storage, no username remapping or profile sign-out', () => {
  const session = readFileSync(new URL('../src/authSession.js', import.meta.url), 'utf8')
  const provider = readFileSync(new URL('../src/components/AuthProvider.jsx', import.meta.url), 'utf8')
  const login = readFileSync(new URL('../src/components/LoginPage.jsx', import.meta.url), 'utf8')
  assert.equal((session.match(/Amplify\.configure\(/g) || []).length, 1)
  assert.match(session, /userPoolId: poolId, userPoolClientId: clientId/)
  assert.match(session, /setKeyValueStorage\(sessionStorage\)/)
  assert.match(provider, /getDisplayIdentity\(await apiRequest\('\/auth\/me'\)\)/)
  const enrichment = session.slice(session.indexOf('export async function getDisplayIdentity'))
  assert.doesNotMatch(enrichment, /signIn\(|signOut\(|configure\(|setKeyValueStorage\(|forceRefresh/)
  assert.match(login, /await login\(email, password\)/)
  assert.match(login, /type="email" autoComplete="username"/)
  assert.match(login, /autoComplete=\{newPassword \? 'new-password' : 'current-password'\}/)
})
