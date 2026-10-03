import { QueryClient } from '@tanstack/react-query'
import type { AuthState } from './api'

export const AUTH_KEY = ['auth'] as const
export const anonymous: AuthState = { user: null, csrfToken: null }

export function safeReturnPath(path: unknown): string {
  return typeof path === 'string' && /^\/(?:chat|history(?:\/[a-zA-Z0-9-]+)?)$/.test(path) ? path : '/'
}

export async function replaceAuth(client: QueryClient, state: AuthState) {
  await client.cancelQueries()
  client.clear()
  client.setQueryData(AUTH_KEY, state)
  sessionStorage.removeItem('member-session-id')
}

export function clearMemberCache(client: QueryClient) {
  const memberData = { predicate: (query: { queryKey: readonly unknown[] }) => query.queryKey[0] !== 'auth' }
  void client.cancelQueries(memberData)
  client.removeQueries(memberData)
  sessionStorage.removeItem('member-session-id')
}
