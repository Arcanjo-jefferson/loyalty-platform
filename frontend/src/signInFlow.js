const PASSWORD_STEP = 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED'

// Own the whole transaction outside the form lifecycle. Amplify owns the opaque
// Cognito session; never copy it, reconfigure Auth, or start signIn during a challenge.
export function createSignInFlow({ signIn, confirmSignIn, acceptSession, endSession }) {
  let step = 'SIGN_IN'
  let busy = false
  const listeners = new Set()
  function update(value) { step = value; listeners.forEach(listener => listener()) }
  async function run(operation) {
    if (busy) throw new Error('A sign-in request is already in progress.')
    busy = true
    try {
      const result = await operation()
      if (result.isSignedIn) {
        update('SIGN_IN')
        await acceptSession()
      } else update(result.nextStep.signInStep)
      return result
    } finally { busy = false }
  }
  return {
    getStep: () => step,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    login(email, password) {
      if (step !== 'SIGN_IN') throw new Error('Finish or cancel the current sign-in first.')
      return run(() => signIn({ username: email.trim(), password, options: { authFlowType: 'USER_SRP_AUTH' } }))
    },
    async completePassword(password) {
      if (step !== PASSWORD_STEP) throw Object.assign(new Error('Sign in again to set your password.'), { name: 'SignInException' })
      try { return await run(() => confirmSignIn({ challengeResponse: password })) }
      catch (error) {
        if (error.name === 'SignInException' || error.name === 'NotAuthorizedException') update('SIGN_IN')
        throw error
      }
    },
    async cancel() {
      if (busy) return
      busy = true
      try { await endSession() }
      finally { update('SIGN_IN'); busy = false }
    },
  }
}

export function signInErrorMessage(error, newPassword = false) {
  if (error.name === 'SignInException' || (newPassword && error.name === 'NotAuthorizedException')) return 'Your sign-in session has expired. Sign in again with your temporary password to continue.'
  if (error.name === 'InvalidPasswordException') return 'Your new password does not meet the password requirements. Choose a stronger password and try again.'
  if (error.name === 'NotAuthorizedException' || error.name === 'UserNotFoundException') return 'Email or password is incorrect.'
  if (error.name === 'PasswordResetRequiredException') return 'A password reset is required. Contact your administrator.'
  if (error.name === 'TooManyRequestsException' || error.name === 'LimitExceededException') return 'Too many attempts. Please wait a moment and try again.'
  return 'Unable to complete sign-in. Please try again. If the problem continues, contact your administrator.'
}
