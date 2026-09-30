import { useState } from 'react'
import Notification from './Notification'
import { birthDateError, irelandToday, latestAdultBirthDate, normalizeIrishMobile } from '../validation'
const empty = { first_name: '', last_name: '', phone: '', date_of_birth: '', email: '', address: '', eircode: '', marketing_consent: false, status: 'active' }
const fields = [['first_name', 'First name', 'text', true], ['last_name', 'Last name', 'text', true], ['phone', 'Phone', 'tel', true], ['date_of_birth', 'Date of birth', 'date', true], ['email', 'Email', 'email'], ['eircode', 'Eircode', 'text'], ['address', 'Address', 'text']]
export default function CustomerForm({ customer, onSave, onCancel }) {
  const [values, setValues] = useState(() => Object.fromEntries(Object.keys(empty).map(key => [key, customer?.[key] ?? empty[key]])))
  const [maxBirthDate] = useState(() => latestAdultBirthDate())
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [fieldErrors, setFieldErrors] = useState({})
  async function submit(event) {
    event.preventDefault()
    setError('')
    const phone = normalizeIrishMobile(values.phone)
    const errors = { phone: phone ? '' : 'Enter a valid Irish mobile number, e.g. 0871234567.', date_of_birth: birthDateError(values.date_of_birth, irelandToday()) }
    setFieldErrors(errors)
    if (Object.values(errors).some(Boolean)) return
    setSaving(true)
    try { await onSave({ ...values, phone }) } catch (err) { setError(err.message === 'Failed to fetch' ? 'Unable to save the customer. Check the backend connection and try again.' : err.message || 'Unable to save the customer. Please try again.') } finally { setSaving(false) }
  }
  return <form noValidate onSubmit={event => {
    const form = event.currentTarget
    // Custom phone/DOB checks give clear errors; other fields retain native constraints.
    const otherInvalid = [...form.elements].find(input => !['phone', 'date_of_birth'].includes(input.name) && input.willValidate && !input.checkValidity())
    if (otherInvalid) { event.preventDefault(); otherInvalid.reportValidity(); return }
    submit(event)
  }} className="panel customer-form">
    <div className="panel-heading"><h2>Customer information</h2><p>Keep contact details accurate and consent clear.</p></div>
    <Notification message={error} variant="error" />
    <fieldset disabled={saving}>
      <div className="form-grid">{fields.map(([key, label, type, required]) => <label key={key} className={key === 'address' ? 'full' : ''}>{label}{required && <span className="required"> *</span>}
        {key === 'phone' ? <div className="phone-input"><span aria-hidden="true">Ireland +353</span><input name="phone" type="tel" inputMode="tel" autoComplete="tel" required value={values.phone} onChange={e => { setValues({ ...values, phone: e.target.value }); setFieldErrors({ ...fieldErrors, phone: '' }) }} maxLength={30} placeholder="0871234567" aria-describedby="phone-help phone-error" aria-invalid={Boolean(fieldErrors.phone)} /></div> : <input name={key} type={type} required={required} value={values[key]} onChange={e => { setValues({ ...values, [key]: e.target.value }); setFieldErrors({ ...fieldErrors, [key]: '' }) }} maxLength={key === 'address' ? 500 : key === 'email' ? 254 : key === 'eircode' ? 10 : type === 'text' ? 100 : undefined} max={type === 'date' ? maxBirthDate : undefined} pattern={key === 'first_name' || key === 'last_name' ? '.*\\S.*' : undefined} aria-describedby={key === 'date_of_birth' ? 'dob-help date_of_birth-error' : undefined} aria-invalid={Boolean(fieldErrors[key])} />}
        {key === 'phone' && <small id="phone-help">Enter an Irish mobile number such as 0871234567. +353871234567 is also accepted.</small>}
        {key === 'date_of_birth' && <small id="dob-help">Customer must be at least 18 years old.</small>}
        {['phone', 'date_of_birth'].includes(key) && <small id={`${key}-error`} className="field-error" role={fieldErrors[key] ? 'alert' : undefined}>{fieldErrors[key]}</small>}
      </label>)}
      {customer && <label>Status<select value={values.status} onChange={e => setValues({ ...values, status: e.target.value })}><option value="active">Active</option><option value="inactive">Inactive</option></select></label>}
      </div>
      <label className="consent"><input type="checkbox" checked={values.marketing_consent} onChange={e => setValues({ ...values, marketing_consent: e.target.checked })} /><span><strong>Promotional SMS consent</strong><small>The customer agrees to receive promotional and marketing SMS from this business. Only select this when the customer has given permission.</small></span></label>
      <div className="form-actions"><button type="button" className="secondary" onClick={onCancel}>Cancel</button><button className="primary" type="submit">{saving ? 'Saving…' : customer ? 'Save changes' : 'Create customer'}</button></div>
    </fieldset>
  </form>
}
