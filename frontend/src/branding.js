// Presentation only. Call with business_id from the backend-verified AuthContext.
// Future branding settings can supply the same configuration shape without
// changing components; this module never reads URL/storage or changes API scope.
export const defaultBranding = Object.freeze({
  name: 'Business workspace', logo: null,
  primary: '#D7B477', accent: '#D7B477', background: '#111C29', surface: '#182635',
  text: '#F1E8D8', muted: '#B4C0CB', primaryText: '#111C29', border: '#728394',
  soft: '#223244', selectedText: '#111C29', focus: '#D7B477',
})
export const businessBranding = Object.freeze({
  trumps: Object.freeze({ name: 'Trumps', logo: '/branding/trumps-logo.png',
    primary: '#77203B', accent: '#D5AC60', background: '#100C0E', surface: '#1C1418',
    text: '#F4E5C9', muted: '#CEBEA5', primaryText: '#F4E5C9', border: '#6D4956',
    soft: '#301D25', selectedText: '#F4E5C9', focus: '#D5AC60' }),
})
export function brandingForBusiness(businessId) {
  return Object.hasOwn(businessBranding, businessId) ? businessBranding[businessId] : defaultBranding
}
export function brandingVariables(branding) {
  return Object.fromEntries(Object.entries(branding).filter(([key]) => !['name', 'logo'].includes(key))
    .map(([key, value]) => [`--theme-${key.replace(/[A-Z]/g, letter => `-${letter.toLowerCase()}`)}`, value]))
}
export function firstNameFromProfile(profile) {
  for (const key of ['given_name', 'name']) {
    if (typeof profile?.[key] !== 'string') continue
    const name = profile[key].replace(/[\r\n\t]/g, ' ').trim().split(/\s+/)[0]
    if (name && name.length <= 60 && [...name].every(char => char.charCodeAt(0) >= 32 && char.charCodeAt(0) !== 127)) return name
  }
  return 'Team member'
}
export function withProfileName(identity, tokenPayload) {
  // A Cognito display profile cannot override verified tenant/role/subject fields.
  return { ...identity, firstName: typeof identity.subject === 'string' && identity.subject.length > 0 && tokenPayload?.sub === identity.subject ? firstNameFromProfile(tokenPayload) : 'Team member' }
}
