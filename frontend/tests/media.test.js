import test from 'node:test'
import assert from 'node:assert/strict'
import { mediaCategories, validateMediaFile, MAX_IMAGE_BYTES, openCamera, stopCamera } from '../src/media.js'
import { createAuthenticatedClient } from '../src/httpClient.js'
test('media controls reflect roles without exposing sensitive categories to Staff', () => {
  for (const role of ['OWNER', 'MANAGER']) assert.deepEqual(mediaCategories(role), ['profile-photo', 'id-document', 'consent-evidence'])
  assert.deepEqual(mediaCategories('STAFF'), ['profile-photo'])
})
test('file input checks supported types and size', () => {
  for (const type of ['image/jpeg', 'image/png', 'image/webp']) assert.equal(validateMediaFile({ type, size: MAX_IMAGE_BYTES }), '')
  assert.match(validateMediaFile({ type: 'image/svg+xml', size: 10 }), /JPEG/)
  assert.match(validateMediaFile({ type: 'image/png', size: MAX_IMAGE_BYTES + 1 }), /5 MiB/)
  assert.match(validateMediaFile({ type: 'image/png', size: 0 }), /non-empty/)
})
test('camera denial and unsupported devices give file-selection fallback', async () => {
  await assert.rejects(openCamera(null, () => true), /Select an image file/)
  await assert.rejects(openCamera({ getUserMedia: async () => { throw Error('permission denied') } }, () => true), /denied/)
})
test('camera requests video only and stops tracks if unmounted before permission completes', async () => {
  let stopped = 0
  const stream = { getTracks: () => [{ stop: () => stopped++ }] }
  const devices = { getUserMedia: async constraints => { assert.equal(constraints.audio, false); return stream } }
  assert.equal(await openCamera(devices, () => false), null)
  assert.equal(stopped, 1)
  assert.equal(await openCamera(devices, () => true), stream)
  stopCamera(stream); assert.equal(stopped, 2)
})
test('image requests use authenticated binary transport with no anonymous image URL', async () => {
  const client = createAuthenticatedClient({ base: 'https://fixture.invalid', getToken: async () => 'fixture-id', onExpired: () => assert.fail(), fetchRequest: async (url, options) => {
    assert.equal(options.headers.Authorization, 'Bearer fixture-id')
    assert.equal(options.responseType, undefined)
    return new Response(new Blob(['image'], { type: 'image/png' }), { headers: { 'Content-Type': 'image/png' } })
  } })
  const blob = await client('/customers/fixture/profile-photo/image', { responseType: 'blob', cache: 'no-store' })
  assert.equal(await blob.text(), 'image')
})
test('uploads preserve binary body and content type, while media 403 remains an authorization error', async () => {
  const blob = new Blob(['fixture'], { type: 'image/png' })
  const client = createAuthenticatedClient({ base: '', getToken: async () => 'fixture-id', onExpired: () => assert.fail(), fetchRequest: async (url, options) => {
    assert.equal(options.body, blob); assert.equal(options.headers['Content-Type'], 'image/png')
    return Response.json({ detail: 'Only Owner or Manager may access this document.' }, { status: 403 })
  } })
  await assert.rejects(client('/customers/fixture/id-document', { method: 'POST', body: blob, headers: { 'Content-Type': 'image/png' } }), error => error.status === 403)
})
