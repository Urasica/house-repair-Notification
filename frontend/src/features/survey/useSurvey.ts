import { useEffect, useMemo, useSyncExternalStore } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../auth/useAuth'
import { getSession } from './api'
import { clearSession, referenceFrom, storedReference, subscribe } from './storage'
import { ApiError } from '../../api/client'

export function useSurvey() {
  const auth = useAuth()
  const client = useQueryClient()
  const member = !!auth.data?.user && !auth.isError
  const raw = useSyncExternalStore(subscribe, () => storedReference(member), () => null)
  const reference = useMemo(() => referenceFrom(raw, member), [raw, member])
  const query = useQuery({ queryKey: ['session', reference?.id], enabled: !!reference && !auth.isPending && !auth.isError,
    queryFn: ({ signal }) => getSession(reference!, signal), retry: false, refetchOnWindowFocus: false })
  useEffect(() => {
    if (!reference) return
    const expire = () => {
      clearSession(reference)
      client.removeQueries({ predicate: q => ['session', 'result', 'questions'].includes(String(q.queryKey[0])) && q.queryKey[1] === reference.id })
    }
    if (query.error instanceof ApiError && ['UNAUTHORIZED', 'SESSION_EXPIRED', 'NOT_FOUND'].includes(query.error.code)) { expire(); return }
    const unavailable = (event: Event) => { if ((event as CustomEvent<{ id: string }>).detail.id === reference.id) expire() }
    window.addEventListener('session-unavailable', unavailable)
    const expiry = query.data?.expiresAt ?? (reference.mode === 'GUEST' && raw ? (JSON.parse(raw) as { expiresAt: string }).expiresAt : null)
    if (!expiry) return () => window.removeEventListener('session-unavailable', unavailable)
    const timer = setTimeout(expire, Math.max(0, Date.parse(expiry) - Date.now()))
    return () => { clearTimeout(timer); window.removeEventListener('session-unavailable', unavailable) }
  }, [reference, raw, query.data?.expiresAt, query.error, client])
  return { auth, reference, query, client }
}
