import { useEffect, useRef } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { getAuth } from './api'
import { AUTH_KEY, anonymous, clearMemberCache } from './state'

export function useAuth() {
  const client = useQueryClient()
  const auth = useQuery({ queryKey: AUTH_KEY, queryFn: ({ signal }) => getAuth(signal), retry: false })
  const previousUser = useRef<string | null | undefined>(auth.data ? auth.data.user?.id ?? null : undefined)
  useEffect(() => {
    if (!auth.data) return
    const user = auth.data.user?.id ?? null
    if (previousUser.current !== undefined && previousUser.current !== user) clearMemberCache(client)
    previousUser.current = user
  }, [auth.data, client])
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
