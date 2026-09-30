export const formatDate = value => value ? new Intl.DateTimeFormat('en-IE', { dateStyle: 'medium' }).format(new Date(value.length === 10 ? `${value}T12:00:00` : value)) : '—'
