import { useState } from 'react'
import { useAuth } from '../AuthContext'
import { authConfigured } from '../authSession'
import { signInErrorMessage } from '../signInFlow'
import Notification from './Notification'

export default function LoginPage() {
  const { login, completePassword, sessionMessage, signInStep, cancelSignIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const newPassword = signInStep === 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED'
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const result = newPassword ? await completePassword(password) : await login(email, password)
      if (!result.isSignedIn) {
        if (result.nextStep.signInStep !== 'CONFIRM_SIGN_IN_WITH_NEW_PASSWORD_REQUIRED') setError('Your account requires an additional sign-in step. Contact your administrator to check the development account configuration.')
      }
    } catch (err) {
      setError(signInErrorMessage(err, newPassword))
    } finally { setPassword(''); setBusy(false) }
  }
  return <main className="login-page"><section className="login-card"><div className="brand"><span className="brand-mark">c</span>Contactly<span className="brand-dot">.</span></div><div className="eyebrow">BUSINESS WORKSPACE</div><h1>{newPassword ? 'Set your password' : 'Welcome back'}</h1><p>{newPassword ? 'Choose a permanent password to finish your first sign-in.' : 'Sign in to manage your customer community.'}</p>
    <Notification message={error || (!authConfigured ? 'Login is not configured. Set the frontend Cognito environment variables and restart Vite.' : '')} variant="error" />
    {sessionMessage && <p role="status" className="login-session">{sessionMessage}</p>}
    <form onSubmit={submit}><fieldset disabled={busy || !authConfigured}>{!newPassword && <label>Email<input type="email" autoComplete="username" required value={email} onChange={event => setEmail(event.target.value)} /></label>}<label>{newPassword ? 'New password' : 'Password'}<input type="password" autoComplete={newPassword ? 'new-password' : 'current-password'} required value={password} onChange={event => setPassword(event.target.value)} /></label><button className="primary" type="submit">{busy ? 'Signing in…' : newPassword ? 'Set password and sign in' : 'Sign in'}</button>{newPassword && <button type="button" onClick={async () => { await cancelSignIn().catch(() => {}); setPassword(''); setError('') }}>Cancel and return to sign in</button>}</fieldset></form><small>Accounts are provided by your business administrator. Public sign-up is unavailable.</small>
  </section></main>
}
