import { useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../../api/client'
import { getAuth } from './api'
import { AUTH_KEY, anonymous, clearMemberCache } from './state'

export function useAuth() {
  const client = useQueryClient()
  const auth = useQuery({ queryKey: AUTH_KEY, queryFn: ({ signal }) => getAuth(signal), retry: false })
  useEffect(() => {
    if (auth.error instanceof ApiError && auth.error.status === 401) {
      clearMemberCache(client)
      client.setQueryData(AUTH_KEY, anonymous)
    }
  }, [auth.error, client])
  return auth
}
