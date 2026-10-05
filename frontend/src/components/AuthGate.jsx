import { useAuth } from '../AuthContext'
import LoginPage from './LoginPage'
import App from '../App'
export default function AuthGate() {
  const { user, loading } = useAuth()
  if (loading) return <main className="login-page"><p role="status">Restoring your session…</p></main>
  return user ? <App key={`${user.subject}:${user.business_id}`} /> : <LoginPage />
}
