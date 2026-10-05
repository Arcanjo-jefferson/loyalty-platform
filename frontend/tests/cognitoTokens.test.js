import test from 'node:test'
import assert from 'node:assert/strict'
import { idTokenFromSession } from '../src/cognitoTokens.js'
test('backend bearer uses ID token when ID and access tokens both exist', () => {
  assert.equal(idTokenFromSession({ tokens: { idToken: { toString: () => 'fixture-id' }, accessToken: { toString: () => 'fixture-access' } } }), 'fixture-id')
})
test('access-only or anonymous sessions cannot send an access token as ID token', () => {
  assert.throws(() => idTokenFromSession({ tokens: { accessToken: { toString: () => 'fixture-access' } } }), /sign in/)
  assert.throws(() => idTokenFromSession({}), /sign in/)
})
