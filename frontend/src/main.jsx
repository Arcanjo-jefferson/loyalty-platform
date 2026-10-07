import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import AuthGate from './components/AuthGate'
import AuthProvider from './components/AuthProvider'
import './App.css'
import PublicQR from './components/PublicQR'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    {window.location.pathname.startsWith('/q/') ? <PublicQR /> : <AuthProvider><AuthGate /></AuthProvider>}
  </StrictMode>,
)
