export const businessId = import.meta.env.VITE_BUSINESS_ID || 'trumps'
const base = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/$/, '')
export async function customerRequest(path = '', options = {}) {
  const response = await fetch(`${base}/customers${path}?business_id=${encodeURIComponent(businessId)}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  const body = await response.json()
  if (!response.ok) {
    const message = Array.isArray(body.detail)
      ? body.detail.map(error => `${error.loc.at(-1)}: ${error.msg}`).join('; ')
      : body.detail || 'Unable to complete this request.'
    throw new Error(message)
  }
  return body
}
