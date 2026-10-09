import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { brandingForBusiness, brandingVariables, defaultBranding, firstNameFromProfile, withProfileName } from '../src/branding.js'
import BrandIdentity from '../src/components/BrandIdentity.js'

test('Trumps configuration supplies original logo and reusable palette', () => {
  const theme = brandingForBusiness('trumps')
  assert.equal(theme.name, 'Trumps'); assert.equal(theme.logo, '/branding/trumps-logo.png')
  assert.deepEqual([theme.primary, theme.accent, theme.background, theme.text], ['#77203B', '#D5AC60', '#100C0E', '#F4E5C9'])
  const html = renderToStaticMarkup(createElement(BrandIdentity, { branding: theme }))
  assert.match(html, /trumps-logo.png/); assert.match(html, /Trumps logo/); assert.match(html, /Loyalty System/)
  assert.equal(brandingVariables(theme)['--theme-primary'], '#77203B')
})

test('unknown and reserved configuration keys get a neutral theme without a Trumps logo', () => {
  for (const business of ['other-business', 'constructor', '__proto__', undefined, 'TRUMPS']) assert.equal(brandingForBusiness(business), defaultBranding)
  const html = renderToStaticMarkup(createElement(BrandIdentity, { branding: defaultBranding }))
  assert.match(html, /Loyalty System/); assert.doesNotMatch(html, /<img|Trumps/)
})

test('Cognito name supports given_name, full name and safe fallback', () => {
  assert.equal(firstNameFromProfile({ given_name: ' Jefferson ' }), 'Jefferson')
  assert.equal(firstNameFromProfile({ name: 'Jane Smith' }), 'Jane')
  for (const profile of [null, {}, { given_name: {} }, { given_name: ' ' }, { name: 'x'.repeat(61) }]) assert.equal(firstNameFromProfile(profile), 'Team member')
})

test('display profile never changes verified role/tenant and must match verified subject', () => {
  const identity = { subject: 'verified-user', business_id: 'other-business', role: 'STAFF' }
  const display = withProfileName(identity, { sub: 'verified-user', given_name: 'Jane', business_id: 'trumps', 'custom:business_id': 'trumps', role: 'OWNER' })
  assert.deepEqual(display, { ...identity, firstName: 'Jane' })
  assert.equal(brandingForBusiness(display.business_id), defaultBranding)
  assert.equal(withProfileName(identity, { sub: 'other-user', given_name: 'Wrong' }).firstName, 'Team member')
  assert.equal(withProfileName(identity, null).firstName, 'Team member')
  assert.equal(withProfileName({}, { given_name: 'Unverified' }).firstName, 'Team member')
})

test('branding is selected from authenticated context and cannot read URL or storage overrides', () => {
  const config = readFileSync(new URL('../src/branding.js', import.meta.url), 'utf8')
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
  const auth = readFileSync(new URL('../src/components/AuthProvider.jsx', import.meta.url), 'utf8')
  assert.doesNotMatch(config, /localStorage|sessionStorage|URLSearchParams|window\.location/)
  assert.match(app, /businessId = user.business_id/)
  assert.match(app, /brandingForBusiness\(businessId\)/)
  assert.match(app, /Welcome, \{user.firstName/)
  assert.match(app, /user.role === 'OWNER'/); assert.match(app, /onClick=\{logout\}/)
  assert.match(auth, /getDisplayIdentity\(await apiRequest\('\/auth\/me'\)\)/)
})

test('logo preserves proportions and themed layout includes responsive navigation', () => {
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
  assert.match(css, /\.business-logo[^}]*height: auto;[^}]*object-fit: contain/)
  assert.match(css, /nav \{ flex-wrap: wrap; \}/)
  assert.match(css, /--theme-primary/); assert.match(css, /--theme-surface/)
  assert.equal(readFileSync(new URL('../index.html', import.meta.url), 'utf8').includes('Contactly'), false)
})


test('authenticated header credit sits below title in every business theme with semantic colours', () => {
  for (const theme of [brandingForBusiness('trumps'), brandingForBusiness('other-business')]) {
    const html = renderToStaticMarkup(createElement(BrandIdentity, { branding: theme, compact: true }))
    assert.match(html, /class="brand-title-group"><span class="wordmark">Loyalty System<\/span><span class="developer-credit">Developed by <span class="developer-credit-name">Avtronics<\/span>/)
  }
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
  assert.match(css, /\.brand-title-group[^}]*flex-direction: column/)
  assert.match(css, /\.developer-credit[^}]*font-family: inherit;[^}]*color: var\(--theme-muted\)/)
  assert.match(css, /\.developer-credit-name[^}]*color: var\(--theme-accent\)/)
  assert.equal(brandingVariables(brandingForBusiness('trumps'))['--theme-accent'], '#D5AC60')
})

test('premium neutral login theme has readable navy, champagne, ivory and slate colours', () => {
  assert.deepEqual([defaultBranding.background, defaultBranding.accent, defaultBranding.text, defaultBranding.muted], ['#111C29', '#D7B477', '#F1E8D8', '#B4C0CB'])
  const luminance = hex => {
    const rgb = hex.slice(1).match(/../g).map(value => parseInt(value, 16) / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4)
    return .2126 * rgb[0] + .7152 * rgb[1] + .0722 * rgb[2]
  }
  const contrast = (a, b) => (Math.max(luminance(a), luminance(b)) + .05) / (Math.min(luminance(a), luminance(b)) + .05)
  for (const colour of [defaultBranding.text, defaultBranding.muted, defaultBranding.accent]) assert.ok(contrast(colour, defaultBranding.surface) >= 4.5)
  assert.ok(contrast(defaultBranding.primaryText, defaultBranding.primary) >= 4.5)
  assert.ok(contrast(defaultBranding.border, defaultBranding.background) >= 3)
})

test('login stays neutral and shares wordmark/credit with responsive premium typography', () => {
  const login = readFileSync(new URL('../src/components/LoginPage.jsx', import.meta.url), 'utf8')
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
  const theme = readFileSync(new URL('../src/theme.css', import.meta.url), 'utf8')
  const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8')
  assert.match(login, /BrandIdentity branding=\{defaultBranding\} compact/)
  assert.doesNotMatch(login, /brandingForBusiness|trumps|business_id/)
  assert.match(theme, /"Outfit"/); assert.match(theme, /"Manrope"/)
  assert.match(html, /Outfit:wght@700/); assert.match(html, /Manrope/); assert.match(html, /display=swap/)
  assert.match(css, /\.login-card \.wordmark \{ font-size: 44px/)
  assert.match(css, /font-size: clamp\(34px, 9vw, 40px\)/)
  const rendered = renderToStaticMarkup(createElement(BrandIdentity, { branding: defaultBranding, compact: true }))
  assert.match(rendered, /Developed by/); assert.match(rendered, /Avtronics/)
  assert.doesNotMatch(rendered, /trumps-logo/)
})

test('all visible platform branding shares Outfit 700 with responsive sizes and Manrope interface', () => {
  const css = readFileSync(new URL('../src/App.css', import.meta.url), 'utf8')
  const theme = readFileSync(new URL('../src/theme.css', import.meta.url), 'utf8')
  const app = readFileSync(new URL('../src/App.jsx', import.meta.url), 'utf8')
  const publicQR = readFileSync(new URL('../src/components/PublicQRView.js', import.meta.url), 'utf8')
  assert.match(css, /\.wordmark \{ font-family: var\(--font-wordmark\); font-weight: 700; letter-spacing: -\.025em;/)
  assert.match(theme, /--font-wordmark: "Outfit", "Manrope", sans-serif/)
  assert.match(theme, /--font-interface: "Manrope"/)
  assert.match(app, /<footer><span className="wordmark">Loyalty System<\/span>/)
  assert.equal((app.match(/<BrandIdentity /g) || []).length, 2, 'sidebar and dashboard header use shared identity')
  assert.match(publicQR, /h\('h1', \{ className: 'wordmark' \}, 'Loyalty System'\)/)
  assert.match(css, /\.header-brand \.wordmark \{ font-size: 28px/)
  assert.match(css, /\.header-brand \.wordmark \{ font-size: 25px/)
  for (const file of ['../src/theme.css', '../index.html', '../src/App.css']) {
    assert.doesNotMatch(readFileSync(new URL(file, import.meta.url), 'utf8'), /Cormorant/)
  }
})
