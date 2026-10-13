import { useState } from 'react'
import PrintJobs from './PrintJobs'
import CustomerVisits from './CustomerVisits'
import CustomerRaffle from './CustomerRaffle'
import CustomerQR from './CustomerQR'
import Vouchers from './Vouchers'
import CustomerPhoto from './CustomerPhoto'
import CustomerMedia from './CustomerMedia'
import { formatDate } from '../format'
import { ConsentBadge } from './CustomerTable'

export default function CustomerProfile({ customer, onEdit }) {
  const [photoVersion, setPhotoVersion] = useState(null)
  const photoRevision = photoVersion?.customerId === customer.customer_id ? photoVersion.revision : null
  const details = [
    ['Phone', customer.phone], ['Date of birth', formatDate(customer.date_of_birth)],
    ['Email', customer.email || 'Not provided'], ['Address', customer.address || 'Not provided'],
    ['Eircode', customer.eircode || 'Not provided'], ['Status', customer.status],
  ]
  return <><section className="panel customer-profile" aria-label="Customer profile">
    <div className="profile-heading"><div className="profile-identity"><CustomerPhoto key={customer.customer_id} customer={customer} revision={photoRevision} /><div><h2>{customer.first_name} {customer.last_name}</h2><p>Customer profile</p></div></div><div className="profile-actions"><ConsentBadge consent={customer.marketing_consent} /><button type="button" className="secondary" onClick={onEdit}>Edit customer</button></div></div>
    <dl className="profile-grid">{details.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  </section><CustomerQR key={`qr-${customer.customer_id}`} customer={customer} /><CustomerVisits key={customer.customer_id} customerId={customer.customer_id} /><CustomerRaffle key={`raffle-${customer.customer_id}`} customerId={customer.customer_id} /><PrintJobs key={`print-${customer.customer_id}`} customerId={customer.customer_id} /><Vouchers key={`vouchers-${customer.customer_id}`} customerId={customer.customer_id} /><CustomerMedia customer={customer} onProfilePhotoSaved={metadata => setPhotoVersion({ customerId: customer.customer_id, revision: metadata.revision })} /></>
}
