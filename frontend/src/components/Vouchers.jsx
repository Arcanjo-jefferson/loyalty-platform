import { useEffect, useState, useSyncExternalStore } from 'react'
import { apiRequest } from '../api'
import { createVoucherFlow } from '../voucherFlow'
import Notification from './Notification'
import VouchersPanel from './VouchersPanel.js'
import './Vouchers.css'

export default function Vouchers({ customerId }) {
  const [flow] = useState(() => createVoucherFlow({ request: apiRequest }))
  const state = useSyncExternalStore(flow.subscribe, flow.getSnapshot)
  const [code, setCode] = useState('')
  const [now, setNow] = useState(Date.now)
  useEffect(() => {
    if (customerId) flow.load(customerId)
    return () => flow.cancel()
  }, [flow, customerId])
  useEffect(() => { const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer) }, [])
  return <VouchersPanel customerId={customerId} state={state} code={code} now={now}
    onCodeChange={value => { setCode(value); flow.clear() }} onLookup={() => flow.lookup(code)}
    onRefresh={() => flow.load(customerId)} onRedeem={voucher => flow.redeem(voucher)}
    notifications={<><Notification message={state.error} variant="error" /><Notification message={state.notice} /></>} />
}
