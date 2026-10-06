import { useEffect, useState, useSyncExternalStore } from 'react'
import { customerRequest } from '../api'
import { createProfilePhotoLoader } from '../profilePhoto'
import ProfileAvatar from './ProfileAvatar'

export default function CustomerPhoto({ customer, revision }) {
  const [loader] = useState(() => createProfilePhotoLoader({ request: customerRequest, customerId: customer.customer_id }))
  const photo = useSyncExternalStore(loader.subscribe, loader.getSnapshot)
  useEffect(() => { loader.load(revision); return () => loader.cancel() }, [loader, revision])
  return <ProfileAvatar customer={customer} photo={photo} onRetry={() => loader.load(revision)} onImageError={loader.imageFailed} />
}
