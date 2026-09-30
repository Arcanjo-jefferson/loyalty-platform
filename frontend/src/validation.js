// Calendar dates use Ireland's business date, independent of the manager's device timezone.
export function irelandToday(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Dublin', year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(now)
  const value = type => parts.find(part => part.type === type).value
  return `${value('year')}-${value('month')}-${value('day')}`
}

export function normalizeIrishMobile(phone) {
  const compact = phone.trim().replace(/[ ().-]/g, '')
  if (/^08[35679][0-9]{7}$/.test(compact)) return `+353${compact.slice(1)}`
  if (/^\+3538[35679][0-9]{7}$/.test(compact)) return compact
  return null
}

export function birthDateError(value, today = irelandToday()) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return 'Enter a valid date of birth.'
  const [year, month, day] = value.split('-').map(Number)
  const parsed = new Date(`${value}T12:00:00Z`)
  if (Number.isNaN(parsed.getTime()) || parsed.getUTCFullYear() !== year || parsed.getUTCMonth() + 1 !== month || parsed.getUTCDate() !== day) return 'Enter a valid date of birth.'
  if (value > today) return 'Date of birth cannot be in the future.'
  const [currentYear, currentMonth, currentDay] = today.split('-').map(Number)
  const age = currentYear - year - (currentMonth < month || currentMonth === month && currentDay < day ? 1 : 0)
  return age < 18 ? 'Customer must be at least 18 years old.' : ''
}

export function latestAdultBirthDate(today = irelandToday()) {
  const [year, month, day] = today.split('-').map(Number)
  // Clamp leap day to the last day of February in the target year.
  const lastDay = new Date(Date.UTC(year - 18, month, 0)).getUTCDate()
  return `${year - 18}-${String(month).padStart(2, '0')}-${String(Math.min(day, lastDay)).padStart(2, '0')}`
}
