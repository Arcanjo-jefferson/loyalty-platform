import { useEffect, useState, useSyncExternalStore } from 'react'
import { signIn, confirmSignIn } from 'aws-amplify/auth'
import { createSignInFlow } from '../signInFlow'
import { AuthContext } from '../AuthContext'
import { apiRequest } from '../api'
import { authConfigured, endSession, getIdToken } from '../authSession'

export default function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(authConfigured)
  const [sessionMessage, setSessionMessage] = useState('')
  useEffect(() => {
    let active = true
    const restore = async () => {
      try {
        await getIdToken()
        const identity = await apiRequest('/auth/me')
        if (active) setUser(identity)
      } catch { /* No authenticated UI is mounted without a verified backend identity. */ }
      finally { if (active) setLoading(false) }
    }
    if (authConfigured) restore()
    const expire = () => { setUser(null); setSessionMessage('Your session expired. Please sign in again.'); endSession().catch(() => {}) }
    window.addEventListener('auth:expired', expire)
    return () => { active = false; window.removeEventListener('auth:expired', expire) }
  }, [])
  async function acceptSession() {
    try { const identity = await apiRequest('/auth/me'); setUser(identity); setSessionMessage('') }
    catch (error) { await endSession().catch(() => {}); throw error }
  }
  const [flow] = useState(() => createSignInFlow({ signIn, confirmSignIn, acceptSession, endSession }))
  const signInStep = useSyncExternalStore(flow.subscribe, flow.getStep)
  const login = flow.login
  const completePassword = flow.completePassword
  const cancelSignIn = flow.cancel
  async function logout() {
    setUser(null)
    setSessionMessage('You have been signed out.')
    await flow.cancel().catch(() => { setSessionMessage('Signed out of this view. Close this tab to clear its session if the connection is unavailable.') })
  }
  return <AuthContext.Provider value={{ user, loading, login, completePassword, logout, sessionMessage, signInStep, cancelSignIn }}>{children}</AuthContext.Provider>
}
