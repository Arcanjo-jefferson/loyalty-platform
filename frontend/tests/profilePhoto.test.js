import test from 'node:test'
import assert from 'node:assert/strict'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import ProfileAvatar from '../src/components/ProfileAvatar.js'
import { createProfilePhotoLoader } from '../src/profilePhoto.js'
import { createAuthenticatedClient } from '../src/httpClient.js'
const customer = { customer_id: 'fixture-id', first_name: 'Fictional', last_name: 'Customer' }
function fixture(request) {
  const created = []; const revoked = []
  const loader = createProfilePhotoLoader({ request, customerId: customer.customer_id, createUrl: blob => { const url = `blob:fixture-${created.length}`; created.push({ blob, url }); return url }, revokeUrl: url => revoked.push(url) })
  return { loader, created, revoked, render: () => renderToStaticMarkup(createElement(ProfileAvatar, { customer, photo: loader.getSnapshot() })) }
}
test('existing profile photo loads automatically through binary endpoint and renders beside identity', async () => {
  const f = fixture(async (path, options) => {
    assert.equal(path, '/fixture-id/profile-photo/image')
    assert.equal(options.responseType, 'blob'); assert.equal(options.cache, 'no-store')
    return new Blob(['fixture-image'], { type: 'image/png' })
  })
  assert.match(f.render(), /Loading profile photo/)
  await f.loader.load()
  assert.match(f.render(), /src="blob:fixture-0"/)
  assert.match(f.render(), /Profile photo of Fictional Customer/)
})
test('missing photo renders initials placeholder without an error', async () => {
  const f = fixture(async () => { throw Object.assign(new Error('No image'), { status: 404 }) })
  await f.loader.load()
  assert.equal(f.loader.getSnapshot().status, 'empty')
  assert.match(f.render(), /No profile photo/); assert.match(f.render(), />FC</)
  assert.doesNotMatch(f.render(), /<img|Retry photo/)
  assert.equal(f.created.length, 0)
})
test('failed retrieval and image decoding show a graceful placeholder and retry', async () => {
  let failed = true
  const f = fixture(async () => { if (failed) throw Error('network unavailable'); return new Blob(['fixture']) })
  await f.loader.load(); assert.equal(f.loader.getSnapshot().status, 'error')
  assert.match(f.render(), /Profile photo unavailable/); assert.match(f.render(), /Retry photo/)
  assert.doesNotMatch(f.render(), /network unavailable/)
  failed = false; await f.loader.load(); f.loader.imageFailed()
  assert.equal(f.loader.getSnapshot().status, 'error'); assert.deepEqual(f.revoked, ['blob:fixture-0'])
})
test('replacement fetches current revision and revokes the previous object URL; unmount releases new URL', async () => {
  const paths = []
  const f = fixture(async path => { paths.push(path); return new Blob(['fixture']) })
  await f.loader.load(); await f.loader.load('new-revision')
  assert.deepEqual(paths, ['/fixture-id/profile-photo/image', '/fixture-id/profile-photo/image?revision=new-revision'])
  assert.deepEqual(f.revoked, ['blob:fixture-0'])
  assert.match(f.render(), /blob:fixture-1/)
  f.loader.cancel(); f.loader.cancel()
  assert.deepEqual(f.revoked, ['blob:fixture-0', 'blob:fixture-1'])
})
test('unmounted or superseded requests never create stale blob URLs', async () => {
  const resolutions = []
  const f = fixture(() => new Promise(resolve => resolutions.push(resolve)))
  const first = f.loader.load(); const second = f.loader.load('new')
  resolutions[1](new Blob(['new'])); await second
  resolutions[0](new Blob(['old'])); await first
  assert.equal(f.created.length, 1)
  const pending = f.loader.load(); f.loader.cancel()
  resolutions[2](new Blob(['late'])); await pending
  assert.equal(f.created.length, 1); assert.deepEqual(f.revoked, ['blob:fixture-0'])
})
test('automatic photo loading requires authentication and never sends an anonymous image request', async () => {
  let expired = 0; let sent = 0
  const denied = createAuthenticatedClient({ base: '', getToken: async () => { throw Error('no session') }, onExpired: () => expired++, fetchRequest: async () => { sent++; assert.fail() } })
  const f = fixture(denied); await f.loader.load()
  assert.equal(expired, 1); assert.equal(sent, 0); assert.equal(f.loader.getSnapshot().status, 'error')
  const authorized = createAuthenticatedClient({ base: '', getToken: async () => 'fixture-id-token', onExpired: () => assert.fail(), fetchRequest: async (path, options) => {
    assert.equal(options.headers.Authorization, 'Bearer fixture-id-token')
    assert.match(path, /profile-photo\/image$/)
    return new Response(new Blob(['fixture'], { type: 'image/png' }))
  } })
  const ready = fixture(authorized); await ready.loader.load(); assert.equal(ready.loader.getSnapshot().status, 'ready')
})
