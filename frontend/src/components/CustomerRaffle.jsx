import { useEffect, useState, useSyncExternalStore } from 'react'
import { apiRequest } from '../api'
import { createRaffleHistory } from '../raffleFlow'
import CustomerRaffleView from './CustomerRaffleView.js'

export default function CustomerRaffle({ customerId }) {
  const [history] = useState(() => createRaffleHistory({ request: apiRequest }))
  const state = useSyncExternalStore(history.subscribe, history.getSnapshot)
  useEffect(() => { history.load(customerId); return () => history.cancel() }, [history, customerId])
  return <CustomerRaffleView state={state} onRefresh={() => history.load(customerId)} />
}
