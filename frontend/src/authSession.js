import { idTokenFromSession } from './cognitoTokens'
import { Amplify } from 'aws-amplify'
import { fetchAuthSession, signOut } from 'aws-amplify/auth'
import { cognitoUserPoolsTokenProvider } from 'aws-amplify/auth/cognito'
import { sessionStorage } from 'aws-amplify/utils'

const poolId = import.meta.env.VITE_COGNITO_USER_POOL_ID
const clientId = import.meta.env.VITE_COGNITO_APP_CLIENT_ID
export const authConfigured = Boolean(poolId && clientId && !poolId.startsWith('replace-') && !clientId.startsWith('replace-'))
if (authConfigured) {
  Amplify.configure({ Auth: { Cognito: { userPoolId: poolId, userPoolClientId: clientId, loginWith: { email: true } } } })
  // Per-tab persistence, not localStorage. No frontend AWS credentials or identity pool.
  cognitoUserPoolsTokenProvider.setKeyValueStorage(sessionStorage)
}
export async function getIdToken(forceRefresh = false) {
  if (!authConfigured) throw new Error('Cognito login is not configured.')
  const session = await fetchAuthSession({ forceRefresh })
  return idTokenFromSession(session)
}
let signingOut = null
export async function endSession() {
  if (!authConfigured) return
  if (!signingOut) signingOut = signOut().finally(() => { signingOut = null })
  await signingOut
}
export function sessionExpired() {
  window.dispatchEvent(new Event('auth:expired'))
}
