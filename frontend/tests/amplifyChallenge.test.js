import test from 'node:test'
import assert from 'node:assert/strict'
import { Amplify } from 'aws-amplify'
import { signIn, confirmSignIn, fetchAuthSession, signOut } from 'aws-amplify/auth'
import { createSignInFlow } from '../src/signInFlow.js'

// Exercise the installed SDK's real in-memory challenge store and token caching.
// All Cognito HTTP responses are synthetic; no AWS account/network is used.
test('installed Amplify confirms the original Cognito session, caches tokens and logs out', async () => {
  const originalFetch = globalThis.fetch
  const requests = []
  let rejectPassword = true
  const jwt = claims => `eyJhbGciOiJSUzI1NiJ9.${Buffer.from(JSON.stringify(claims)).toString('base64url')}.test`
  const claims = { sub: 'fixture-owner', iat: Math.floor(Date.now() / 1000), exp: Math.floor(Date.now() / 1000) + 3600 }
  globalThis.fetch = async (input, options) => {
    const request = input instanceof Request ? input : new Request(input, options)
    const body = await request.json()
    const operation = request.headers.get('x-amz-target').split('.').at(-1)
    requests.push({ operation, body })
    if (operation === 'InitiateAuth') return Response.json({ ChallengeName: 'NEW_PASSWORD_REQUIRED', Session: 'opaque-test-session', ChallengeParameters: { USERNAME: 'fixture-owner', requiredAttributes: '[]' } })
    if (operation === 'RespondToAuthChallenge') {
      assert.equal(body.Session, 'opaque-test-session')
      assert.equal(body.ChallengeName, 'NEW_PASSWORD_REQUIRED')
      if (rejectPassword) return Response.json({ __type: 'InvalidPasswordException', message: 'Test policy failure' }, { status: 400 })
      return Response.json({ AuthenticationResult: { AccessToken: jwt({ ...claims, username: 'fixture-owner', token_use: 'access' }), IdToken: jwt({ ...claims, token_use: 'id' }), RefreshToken: 'test-refresh', ExpiresIn: 3600, TokenType: 'Bearer' } })
    }
    if (operation === 'RevokeToken') return Response.json({})
    assert.fail(`Unexpected operation ${operation}`)
  }
  try {
    Amplify.configure({ Auth: { Cognito: { userPoolId: 'eu-west-1_TestPool', userPoolClientId: 'fixtureclient' } } })
    let accepted = false
    const flow = createSignInFlow({ signIn, confirmSignIn, endSession: signOut, acceptSession: async () => { assert.ok((await fetchAuthSession()).tokens.idToken); accepted = true } })
    await flow.login('owner@example.test', 'temporary')
    assert.equal(flow.getStep(), 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED')
    await assert.rejects(flow.completePassword('weak'), { name: 'InvalidPasswordException' })
    assert.equal(accepted, false)
    rejectPassword = false
    await flow.completePassword('Permanent-password1!')
    assert.equal(accepted, true)
    assert.equal(requests.filter(r => r.operation === 'InitiateAuth').length, 1)
    await flow.cancel()
    assert.equal((await fetchAuthSession()).tokens, undefined)
  } finally { globalThis.fetch = originalFetch }
})
