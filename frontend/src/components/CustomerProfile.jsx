import CustomerMedia from './CustomerMedia'
import { formatDate } from '../format'
import { ConsentBadge } from './CustomerTable'

export default function CustomerProfile({ customer, onEdit }) {
  const details = [
    ['Phone', customer.phone], ['Date of birth', formatDate(customer.date_of_birth)],
    ['Email', customer.email || 'Not provided'], ['Address', customer.address || 'Not provided'],
    ['Eircode', customer.eircode || 'Not provided'], ['Status', customer.status],
  ]
  return <><section className="panel customer-profile" aria-label="Customer profile">
    <div className="profile-heading"><div><h2>{customer.first_name} {customer.last_name}</h2><p>Customer profile</p></div><div className="profile-actions"><ConsentBadge consent={customer.marketing_consent} /><button type="button" className="secondary" onClick={onEdit}>Edit customer</button></div></div>
    <dl className="profile-grid">{details.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>
  </section><CustomerMedia customer={customer} /></>
}
