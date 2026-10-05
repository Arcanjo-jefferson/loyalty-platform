/** Injectable authenticated transport; never chooses a tenant from client input. */
export function createAuthenticatedClient({ base, getToken, onExpired, fetchRequest = fetch }) {
  return async function request(path, options = {}) {
    const expired = () => { onExpired(); return new Error('Your session has expired. Please sign in again.') }
    let token
    try { token = await getToken() } catch { throw expired() }
    const send = value => fetchRequest(`${base}${path}`, { ...options, headers: { 'Content-Type': 'application/json', ...options.headers, Authorization: `Bearer ${value}` } })
    let response = await send(token)
    if (response.status === 401) {
      let refreshed
      try { refreshed = await getToken(true) } catch { throw expired() }
      response = await send(refreshed)
      if (response.status === 401) throw expired()
    }
    const body = await response.json()
    if (!response.ok) {
      const message = Array.isArray(body.detail) ? body.detail.map(error => `${error.loc.at(-1)}: ${error.msg}`).join('; ') : body.detail || 'Unable to complete this request.'
      throw new Error(message)
    }
    return body
  }
}
