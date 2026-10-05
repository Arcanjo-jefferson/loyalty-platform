// The backend verifies ID tokens: access tokens are never a fallback.
export function idTokenFromSession(session) {
  if (!session.tokens?.idToken) throw new Error('Please sign in.')
  return session.tokens.idToken.toString()
}
