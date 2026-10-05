import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import AuthGate from './components/AuthGate'
import AuthProvider from './components/AuthProvider'
import './App.css'

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <AuthProvider><AuthGate /></AuthProvider>
  </StrictMode>,
)
