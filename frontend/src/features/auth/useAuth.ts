import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { getAuth } from './api'
import type { AuthState } from './api'
import { AUTH_KEY, anonymous, clearMemberCache } from './state'

export function useAuth() {
  const client = useQueryClient()
  const auth = useQuery({ queryKey: AUTH_KEY, queryFn: async ({ signal }) => {
    const next = await getAuth(signal)
    const previous = client.getQueryData<AuthState>(AUTH_KEY)
    // Clear the old identity before publishing the new one and mounting its queries.
    if (!signal.aborted && previous && previous.user?.id !== next.user?.id) clearMemberCache(client)
    return next
  }, retry: false })
  useEffect(() => {
    if (auth.error instanceof ApiError && auth.error.status === 401) {
      clearMemberCache(client)
      client.setQueryData(AUTH_KEY, anonymous)
    }
  }, [auth.error, client])
  useEffect(() => {
    const expire = () => { clearMemberCache(client); client.setQueryData(AUTH_KEY, anonymous) }
    window.addEventListener('auth-expired', expire)
    return () => window.removeEventListener('auth-expired', expire)
  }, [client])
  return auth
}
