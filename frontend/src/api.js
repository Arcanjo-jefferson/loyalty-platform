import { getIdToken, sessionExpired } from './authSession'
import { createAuthenticatedClient } from './httpClient'
const base = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
export const apiRequest = createAuthenticatedClient({ base, getToken: getIdToken, onExpired: sessionExpired })
export const customerRequest = (path = '', options = {}) => apiRequest(`/customers${path}`, options)
