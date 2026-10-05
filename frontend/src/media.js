export const MAX_IMAGE_BYTES = 5 * 1024 * 1024
export const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp']
export const DOCUMENT_TYPES = ['Passport', 'Driving Licence', 'National ID', 'Residence Permit', 'Other']
export function validateMediaFile(file) {
  if (!file || !IMAGE_TYPES.includes(file.type)) return 'Select a JPEG, PNG or WebP image.'
  if (file.size > MAX_IMAGE_BYTES) return 'Image must be 5 MiB or smaller.'
  if (!file.size) return 'Select a non-empty image.'
  return ''
}
export function mediaCategories(role) {
  return role === 'OWNER' || role === 'MANAGER' ? ['profile-photo', 'id-document', 'consent-evidence'] : ['profile-photo']
}
export function stopCamera(stream) { stream?.getTracks().forEach(track => track.stop()) }
export async function openCamera(mediaDevices, stillActive) {
  if (!mediaDevices?.getUserMedia) throw new Error('Camera is unavailable. Select an image file instead.')
  try {
    const stream = await mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
    if (!stillActive()) { stopCamera(stream); return null }
    return stream
  } catch {
    throw new Error('Camera access is unavailable or was denied. Select an image file instead.')
  }
}
