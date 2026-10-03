import type { components } from '../../api/generated/schema'
import { api } from '../../api/client'

export type AuthState = components['schemas']['AuthState']
export type Credentials = components['schemas']['Credentials']

export const getAuth = (signal?: AbortSignal) => api<AuthState>('/auth/me', { signal })
export const login = (body: Credentials) => api<AuthState>('/auth/login', { method: 'POST', body: JSON.stringify(body) })
export const register = (body: Credentials) => api<components['schemas']['User']>('/auth/register', { method: 'POST', body: JSON.stringify(body) })
export const logout = (csrf: string) => api<void>('/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrf } })
