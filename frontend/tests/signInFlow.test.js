import test from 'node:test'
import assert from 'node:assert/strict'
import { createSignInFlow, signInErrorMessage } from '../src/signInFlow.js'
const challenge = { isSignedIn: false, nextStep: { signInStep: 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED' } }
const done = { isSignedIn: true, nextStep: { signInStep: 'DONE' } }
function setup() {
  const calls = []; let transaction = false; let failure = null
  const flow = createSignInFlow({
    signIn: async input => { calls.push(['signIn', input]); transaction = true; return input.password === 'temporary' ? challenge : done },
    confirmSignIn: async input => { assert.equal(transaction, true); calls.push(['confirmSignIn', input]); if (failure) throw failure; transaction = false; return done },
    acceptSession: async () => calls.push(['session']),
    endSession: async () => { calls.push(['signOut']); transaction = false },
  })
  return { flow, calls, fail: error => { failure = error } }
}
test('normal login accepts session without a preliminary logout', async () => {
  const { flow, calls } = setup(); await flow.login(' owner@example.test ', 'permanent')
  assert.deepEqual(calls.map(c => c[0]), ['signIn', 'session'])
  assert.equal(calls[0][1].username, 'owner@example.test')
  assert.equal(calls[0][1].options.authFlowType, 'USER_SRP_AUTH')
})
test('NEW_PASSWORD_REQUIRED retains transaction across view subscriptions and confirms successfully', async () => {
  const { flow, calls } = setup(); await flow.login('owner@example.test', 'temporary')
  assert.equal(flow.getStep(), challenge.nextStep.signInStep)
  flow.subscribe(() => {})()
  assert.throws(() => flow.login('owner@example.test', 'temporary'))
  await flow.completePassword('new-permanent')
  assert.deepEqual(calls.map(c => c[0]), ['signIn', 'confirmSignIn', 'session'])
  assert.deepEqual(calls[1][1], { challengeResponse: 'new-permanent' })
  assert.equal(flow.getStep(), 'SIGN_IN')
})
test('failed password confirmation retains challenge for retry and does not accept session', async () => {
  const { flow, calls, fail } = setup(); await flow.login('owner@example.test', 'temporary')
  fail(Object.assign(new Error('internal'), { name: 'InvalidPasswordException' }))
  await assert.rejects(flow.completePassword('weak'))
  assert.equal(flow.getStep(), challenge.nextStep.signInStep)
  assert.equal(calls.some(c => c[0] === 'session'), false)
  fail(null); await flow.completePassword('strong-password')
  assert.equal(calls.at(-1)[0], 'session')
})
test('cancel/logout abandons challenge and permits fresh login', async () => {
  const { flow, calls } = setup(); await flow.login('owner@example.test', 'temporary'); await flow.cancel()
  assert.equal(flow.getStep(), 'SIGN_IN')
  await assert.rejects(flow.completePassword('password'), { name: 'SignInException' })
  await flow.login('owner@example.test', 'temporary')
  assert.deepEqual(calls.map(c => c[0]), ['signIn', 'signOut', 'signIn'])
})
test('lost SDK transaction returns to login with friendly error', async () => {
  const { flow, fail, calls } = setup(); await flow.login('owner@example.test', 'temporary')
  const error = Object.assign(new Error('signIn was not called before confirmSignIn'), { name: 'SignInException' }); fail(error)
  await assert.rejects(flow.completePassword('password'))
  assert.equal(flow.getStep(), 'SIGN_IN'); assert.equal(calls.some(c => c[0] === 'session'), false)
  assert.doesNotMatch(signInErrorMessage(error, true), /confirmSignIn/)
})
test('overlapping requests cannot restart or cancel an in-flight transaction', async () => {
  let release
  const flow = createSignInFlow({ signIn: () => new Promise(resolve => { release = resolve }), confirmSignIn: async () => done, acceptSession: async () => {}, endSession: async () => assert.fail('unexpected cancellation') })
  const first = flow.login('owner@example.test', 'temporary')
  await assert.rejects(flow.login('owner@example.test', 'temporary'), /in progress/); await flow.cancel()
  release(challenge); await first; assert.equal(flow.getStep(), challenge.nextStep.signInStep)
})
test('unknown internal troubleshooting is never exposed', () => {
  assert.doesNotMatch(signInErrorMessage(new Error('private troubleshooting')), /private troubleshooting/)
})
