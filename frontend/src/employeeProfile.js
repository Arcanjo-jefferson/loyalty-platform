import { firstNameFromProfile, withProfileName } from './branding.js'

// Display-only enrichment. Backend-verified identity remains authoritative.
// No profile cache: each login/restoration resolves the current employee.
export async function loadEmployeeIdentity(identity, { fetchAuthSession, fetchUserAttributes }) {
  const fallback = () => withProfileName(identity, null)
  try {
    const payload = (await fetchAuthSession()).tokens?.idToken?.payload
    if (!identity.subject || payload?.sub !== identity.subject) return fallback()
    let profile = payload
    if (firstNameFromProfile(payload) === 'Team member') {
      try {
        const attributes = await fetchUserAttributes()
        if (attributes?.sub === identity.subject) profile = { ...payload, given_name: attributes.given_name, name: attributes.name }
      } catch { /* Missing/unavailable profile must not prevent authenticated access. */ }
    }
    // An employee may sign out while the profile request is in flight.
    const current = (await fetchAuthSession()).tokens?.idToken?.payload
    if (current?.sub !== identity.subject) return fallback()
    return withProfileName(identity, profile)
  } catch { return fallback() }
}
