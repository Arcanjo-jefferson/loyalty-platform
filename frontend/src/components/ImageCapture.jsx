import { useEffect, useRef, useState } from 'react'
import { openCamera, stopCamera, validateMediaFile } from '../media'
import Notification from './Notification'

export default function ImageCapture({ onSelect, disabled, label }) {
  const [stream, setStream] = useState(null)
  const [starting, setStarting] = useState(false)
  const [capture, setCapture] = useState(null)
  const [error, setError] = useState('')
  const video = useRef(null)
  const currentStream = useRef(null)
  const generation = useRef(0)
  useEffect(() => () => { generation.current++; stopCamera(currentStream.current) }, [])
  useEffect(() => { if (video.current) video.current.srcObject = stream }, [stream])
  useEffect(() => () => { if (capture) URL.revokeObjectURL(capture.url) }, [capture])
  function showCapture(blob) { setCapture({ blob, url: URL.createObjectURL(blob) }) }
  function closeCamera() { generation.current++; stopCamera(currentStream.current); currentStream.current = null; setStream(null) }
  async function start() {
    const attempt = ++generation.current
    setStarting(true); setError(''); setCapture(null); onSelect(null)
    try {
      const camera = await openCamera(navigator.mediaDevices, () => generation.current === attempt)
      if (camera) { currentStream.current = camera; setStream(camera) }
    } catch (err) { if (generation.current === attempt) setError(err.message) }
    finally { if (generation.current === attempt) setStarting(false) }
  }
  async function takePhoto() {
    const element = video.current
    if (!element?.videoWidth) { setError('Camera is still starting. Please try again.'); return }
    const attempt = generation.current
    const canvas = document.createElement('canvas')
    const scale = Math.min(1, 2400 / Math.max(element.videoWidth, element.videoHeight))
    canvas.width = Math.round(element.videoWidth * scale); canvas.height = Math.round(element.videoHeight * scale)
    canvas.getContext('2d').drawImage(element, 0, 0, canvas.width, canvas.height)
    const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', 0.9))
    if (generation.current !== attempt) return
    const message = validateMediaFile(blob)
    if (message) { setError(message); return }
    showCapture(blob); onSelect(blob); closeCamera()
  }
  function selectFile(event) {
    const file = event.target.files?.[0]
    if (!file) return
    closeCamera()
    const message = validateMediaFile(file)
    setError(message)
    if (message) { setCapture(null); onSelect(null); return }
    showCapture(file); onSelect(file)
    event.target.value = ''
  }
  return <div className="image-capture">
    <Notification message={error} variant="error" />
    <label className="media-file">Select {label.toLowerCase()} image<input type="file" accept="image/jpeg,image/png,image/webp" disabled={disabled || starting} onChange={selectFile} /></label>
    {!stream && <button type="button" className="secondary" disabled={disabled || starting} onClick={start}>{starting ? 'Opening camera…' : capture ? 'Retake with camera' : 'Use camera'}</button>}
    {stream && <><video ref={video} autoPlay muted playsInline aria-label={`${label} camera preview`} /><div className="media-actions"><button type="button" className="secondary" disabled={disabled} onClick={takePhoto}>Capture photo</button><button type="button" className="secondary" onClick={closeCamera}>Close camera</button></div></>}
    {capture && <div><p>Selected image · review before uploading</p><img className="media-image" src={capture.url} alt={`${label} selected for upload`} /></div>}
  </div>
}
