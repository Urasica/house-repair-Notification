import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { createSession, getCatalog } from './api'
import { clearSession, identityEpoch, storeSession } from './storage'
import { useSurvey } from './useSurvey'

export function useStartSurvey() {
  const { auth, reference, query, client } = useSurvey()
  const catalog = useQuery({ queryKey: ['catalog-ready'], queryFn: () => getCatalog(), retry: false })
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const guard = useRef(false)
  async function start() {
    if (!catalog.data || guard.current || auth.isError || auth.isPending) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null)
    try {
      const created = await createSession(catalog.data.version, auth.data?.csrfToken)
      if (identityEpoch() !== epoch) return
      const surveyQueries = { predicate: (q: { queryKey: readonly unknown[] }) => ['session', 'result', 'questions'].includes(String(q.queryKey[0])) }
      await client.cancelQueries(surveyQueries)
      if (identityEpoch() !== epoch) return
      client.removeQueries(surveyQueries)
      if (reference) clearSession(reference)
      storeSession(created.session, created.sessionToken)
      client.setQueryData(['session', created.session.id, auth.data?.user?.id ?? null, 'SURVEY'], created.session)
      void navigate('/select')
    } catch (cause) {
      if (identityEpoch() !== epoch) return
      setError(cause)
      if (cause instanceof ApiError && cause.code === 'CATALOG_UPDATED') void catalog.refetch()
    } finally { guard.current = false; if (identityEpoch() === epoch) setBusy(false) }
  }
  return { auth, reference, query, catalog, busy, error, start }
}
