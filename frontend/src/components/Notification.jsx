/** Persistent, accessible feedback for completed actions and recoverable errors. */
export default function Notification({ message, variant = 'success', onDismiss }) {
  const isError = variant === 'error'
  return <div className={message ? `notification notification--${isError ? 'error' : 'success'}` : undefined}>
    <div role={isError ? 'alert' : 'status'} aria-live={isError ? 'assertive' : 'polite'} aria-atomic="true">
      {message && <><span className="notification-icon" aria-hidden="true">{isError ? '!' : '✓'}</span><span>{message}</span></>}
    </div>
    {message && onDismiss && <button type="button" className="notification-dismiss" aria-label="Dismiss notification" onClick={onDismiss}>×</button>}
  </div>
}
