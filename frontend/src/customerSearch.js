import { normalizeIrishMobile } from './validation.js'
// Directory results already come from the authenticated, business-scoped API.
export function searchCustomers(customers, query) {
  const text = query.trim().toLowerCase().replace(/\s+/g, ' ')
  if (!text) return customers
  const compact = query.replace(/[\s().-]/g, '')
  // Search accepts missing national/country prefixes; form validation stays strict.
  const phone = normalizeIrishMobile(compact)
    || normalizeIrishMobile(`0${compact}`)
    || normalizeIrishMobile(`+${compact}`)
    || (/^08[35679]\d*$/.test(compact) ? compact.slice(1) : compact)
  return customers.filter(customer => `${customer.first_name} ${customer.last_name}`.toLowerCase().replace(/\s+/g, ' ').includes(text)
    || customer.phone.includes(phone) || customer.phone.includes(text))
}
