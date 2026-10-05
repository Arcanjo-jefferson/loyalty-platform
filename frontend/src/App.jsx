import { useEffect, useRef, useState } from 'react'
import { customerRequest } from './api'
import { useAuth } from './AuthContext'
import CustomerForm from './components/CustomerForm'
import CustomerProfile from './components/CustomerProfile'
import Notification from './components/Notification'
import CustomerTable from './components/CustomerTable'
import { formatDate } from './format'
import './App.css'

function readRoute() {
  const path = window.location.hash.slice(1) || '/'
  return path === '/customers/new' ? { page: 'new' } : path.startsWith('/customers/') ? { page: path.endsWith('/edit') ? 'edit' : 'detail', id: path.split('/')[2] } : { page: path === '/customers' ? 'customers' : 'dashboard' }
}
export default function App() {
  const { user, logout } = useAuth()
  const businessId = user.business_id
  const [today] = useState(() => new Date())
  const [route, setRoute] = useState(readRoute)
  const [customers, setCustomers] = useState([])
  const [customer, setCustomer] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [notice, setNotice] = useState('')
  const savedProfile = useRef(null)
  const [retry, setRetry] = useState(0)
  useEffect(() => {
    const change = () => {
      const next = readRoute()
      const saved = savedProfile.current
      const showSaved = next.page === 'detail' && next.id === saved?.customer.customer_id
      // Render the canonical POST/PUT response immediately, without a stale follow-up fetch.
      setCustomer(showSaved ? saved.customer : null)
      setLoading(!showSaved)
      setError('')
      setNotice(showSaved ? saved.message : '')
      setRoute(showSaved ? { ...next, savedCustomer: saved.customer } : next)
      savedProfile.current = null
    }
    window.addEventListener('hashchange', change)
    return () => window.removeEventListener('hashchange', change)
  }, [])
  useEffect(() => {
    if (route.savedCustomer) return
    let active = true
    const request = ['detail', 'edit'].includes(route.page) ? customerRequest(`/${encodeURIComponent(route.id)}`) : customerRequest()
    request.then(data => { if (active) { if (['detail', 'edit'].includes(route.page)) setCustomer(data); else setCustomers(data) } }).catch(err => { if (active) setError(err.message === 'Failed to fetch' ? 'Cannot reach the API. Check that the backend is running on port 8000.' : err.message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [route, retry])
  const navigate = path => { window.location.hash = path }
  const openCustomer = id => navigate(`/customers/${id}`)
  async function save(values) {
    const editing = route.page === 'edit'
    setNotice('')
    const saved = await customerRequest(editing ? `/${encodeURIComponent(route.id)}` : '', {
      method: editing ? 'PUT' : 'POST', body: JSON.stringify(values),
    })
    savedProfile.current = {
      customer: saved,
      message: editing ? 'Customer details updated successfully.' : 'Customer registered successfully.',
    }
    navigate(`/customers/${saved.customer_id}`)
  }
  const filtered = customers.filter(c => `${c.first_name} ${c.last_name} ${c.phone}`.toLowerCase().includes(search.toLowerCase()))
  const birthdays = customers.filter(c => Number(c.date_of_birth.slice(5, 7)) === today.getMonth() + 1).length
  const titles = { dashboard: 'Dashboard', customers: 'Customers', new: 'Add customer', detail: 'Customer details', edit: 'Edit customer' }
  return <div className="app-shell">
    <aside className="sidebar"><a className="brand" href="#/"><span className="brand-mark">c</span>Contactly<span className="brand-dot">.</span></a><div className="workspace"><span className="workspace-icon">{businessId[0].toUpperCase()}</span><div><strong>{businessId}</strong><small>{user.role.toLowerCase()} workspace</small></div></div><div className="nav-label">WORKSPACE</div><nav aria-label="Main navigation">{[['dashboard', '/', '◫', 'Dashboard'], ['customers', '/customers', '♙', 'Customers']].map(([page, path, icon, label]) => <a key={page} href={`#${path}`} className={route.page === page || page === 'customers' && ['new', 'detail', 'edit'].includes(route.page) ? 'selected' : ''}><span aria-hidden="true">{icon}</span>{label}</a>)}{['Messaging', 'Loyalty', 'Vouchers', 'Settings'].map(label => <button disabled key={label}><span aria-hidden="true">○</span>{label}<small>Soon</small></button>)}</nav><div className="sidebar-foot"><span className="local-dot" /> Local development<small>Customer foundation · Milestone 1</small></div></aside>
    <div className="main-shell"><header className="topbar"><span>Workspace <span className="divider">/</span> {titles[route.page]}</span><div className="session-controls"><span className="environment">{user.role}</span><button type="button" className="secondary" onClick={logout}>Sign out</button></div></header><main><div className="page-heading"><div><div className="eyebrow">YOUR CUSTOMER COMMUNITY</div><h1>{titles[route.page]}</h1><p>{route.page === 'dashboard' ? 'A clear view of the people behind your business.' : route.page === 'customers' ? 'Manage your contacts and their marketing preferences.' : 'Personal details, contact information and SMS preferences.'}</p></div>{['dashboard', 'customers'].includes(route.page) && <button className="primary" onClick={() => navigate('/customers/new')}>＋ Add customer</button>}</div>
      <div className="local-note">Development workspace · Use fictional customer data only.</div>
      <Notification message={notice} onDismiss={() => setNotice('')} />
      {loading ? <div className="panel empty" role="status">Loading customer information…</div> : error ? <div className="panel empty"><p role="alert">{error}</p><button className="secondary" onClick={() => { setLoading(true); setError(''); setRetry(retry + 1) }}>Try again</button></div> : <>
        {route.page === 'dashboard' && <><div className="stats">{[['Total customers', customers.length, 'All registered contacts', '♙'], ['Marketing opted-in', customers.filter(c => c.marketing_consent).length, 'Consent for promotional SMS', '✓'], ['Birthdays this month', birthdays, new Intl.DateTimeFormat('en-IE', { month: 'long' }).format(today), '◇']].map(([label, value, caption, icon]) => <section className="panel stat" key={label}><div className="stat-label">{label}<span aria-hidden="true">{icon}</span></div><div className="stat-value">{value}</div><small>{caption}</small></section>)}</div><section className="panel"><div className="section-heading"><div><h2>Recently added customers</h2><p>Your latest connections, all in one place.</p></div><a href="#/customers">View all customers →</a></div>{customers.length ? <CustomerTable customers={[...customers].sort((a, b) => b.created_at.localeCompare(a.created_at)).slice(0, 5)} onOpen={openCustomer} /> : <div className="empty"><span className="empty-icon">♙</span><h2>Your community starts here</h2><p>Add your first customer to start building your customer directory.</p><button className="primary" onClick={() => navigate('/customers/new')}>Add your first customer</button></div>}</section><div className="foundation"><div><h2>Good relationships start with good records.</h2><p>Keep your customer details up to date and record promotional SMS consent with care.</p></div><span className="foundation-mark" aria-hidden="true">↗</span></div></>}
        {route.page === 'customers' && <section className="panel"><div className="section-heading"><h2>Customer directory <span className="count">{customers.length}</span></h2><label className="search"><span className="sr-only">Search customers by name or phone</span><input type="search" placeholder="Search name or phone…" value={search} onChange={e => setSearch(e.target.value)} /></label></div>{filtered.length ? <CustomerTable customers={filtered} onOpen={openCustomer} /> : <div className="empty"><h2>{search ? 'No matching customers' : 'No customers yet'}</h2><p>{search ? 'Try a different name or phone number.' : 'Add your first customer to get started.'}</p></div>}<div className="table-footer">{filtered.length} customer{filtered.length === 1 ? '' : 's'}{search && ` matching “${search}”`}</div></section>}
        {['new', 'detail', 'edit'].includes(route.page) && <>
          <a className="back-link" href={route.page === 'edit' ? `#/customers/${route.id}` : '#/customers'}>← {route.page === 'edit' ? 'Back to customer profile' : 'Back to customers'}</a>
          {route.page === 'detail' && customer && <CustomerProfile customer={customer} onEdit={() => navigate(`/customers/${customer.customer_id}/edit`)} />}
          {['new', 'edit'].includes(route.page) && <CustomerForm key={customer?.customer_id || 'new'} customer={route.page === 'edit' ? customer : null} canChangeStatus={user.role !== 'STAFF'} onSave={save} onCancel={() => navigate(route.page === 'edit' ? `/customers/${route.id}` : '/customers')} />}
          {route.page === 'detail' && customer && <section className="panel record-info"><h2>Record information</h2><dl><div><dt>Created</dt><dd>{formatDate(customer.created_at)}</dd></div><div><dt>Last updated</dt><dd>{formatDate(customer.updated_at)}</dd></div><div><dt>Last consent change</dt><dd>{formatDate(customer.consent_timestamp)}</dd></div></dl></section>}
        </>}
      </>}
    </main><footer>Contactly · Customer management <span>Milestone 3</span></footer></div>
  </div>
}
