import { QueryClient } from '@tanstack/react-query'
import type { AuthState } from './api'
import { resetSurveyIdentity } from '../survey/storage'

export const AUTH_KEY = ['auth'] as const
export const anonymous: AuthState = { user: null, csrfToken: null }

export function safeReturnPath(path: unknown): string {
  return typeof path === 'string' && /^\/(?:chat|history(?:\/[a-zA-Z0-9-]+)?)$/.test(path) ? path : '/'
}

export async function replaceAuth(client: QueryClient, state: AuthState) {
  resetSurveyIdentity()
  await client.cancelQueries()
  client.removeQueries({ predicate: query => query.queryKey[0] !== AUTH_KEY[0] })
  client.setQueryData(AUTH_KEY, state)
}

export function clearMemberCache(client: QueryClient) {
  // Public catalog queries can mount while the identity-change effect runs.
  // Cancelling/removing their active observer leaves the new home screen pending.
  const memberData = { predicate: (query: { queryKey: readonly unknown[] }) => !['auth', 'catalog-ready', 'catalog'].includes(String(query.queryKey[0])) }
  void client.cancelQueries(memberData)
  client.removeQueries(memberData)
  resetSurveyIdentity()
}
