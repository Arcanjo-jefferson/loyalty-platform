// One authenticated image request per profile opening/replacement. No persistent
// cache: each view owns its blob URL and releases it when its lifetime ends.
export function createProfilePhotoLoader({ request, customerId, createUrl = URL.createObjectURL, revokeUrl = URL.revokeObjectURL }) {
  let snapshot = { status: 'loading', url: '' }
  let generation = 0
  let activeRequest = null
  const listeners = new Set()
  function publish(value) { snapshot = value; listeners.forEach(listener => listener()) }
  function release() { if (snapshot.url) revokeUrl(snapshot.url) }
  return {
    getSnapshot: () => snapshot,
    subscribe(listener) { listeners.add(listener); return () => listeners.delete(listener) },
    async load(revision) {
      const attempt = ++generation
      activeRequest?.abort()
      activeRequest = new AbortController()
      release(); publish({ status: 'loading', url: '' })
      try {
        const query = revision ? `?revision=${encodeURIComponent(revision)}` : ''
        const blob = await request(`/${encodeURIComponent(customerId)}/profile-photo/image${query}`, { responseType: 'blob', cache: 'no-store', signal: activeRequest.signal })
        if (generation !== attempt) return
        publish({ status: 'ready', url: createUrl(blob) })
      } catch (error) {
        if (generation === attempt) publish({ status: error.status === 404 ? 'empty' : 'error', url: '' })
      }
    },
    cancel() { ++generation; activeRequest?.abort(); release(); snapshot = { status: 'loading', url: '' } },
    imageFailed() { ++generation; release(); publish({ status: 'error', url: '' }) },
  }
}
