import type { components } from '../../api/generated/schema'
import { api } from '../../api/client'
import type { Catalog, Context, Guidance, Pending, Session, SessionRef } from './storage'

export type Questions = components['schemas']['QuestionsResponse']
export type RequestState = components['schemas']['RequestState']
export type History = components['schemas']['ResultList']

export function headers(reference: SessionRef, csrf: string | null | undefined): Record<string, string> {
  return reference.mode === 'GUEST' ? { Authorization: 'Bearer ' + reference.token } : csrf ? { 'X-CSRF-Token': csrf } : {}
}
export const getCatalog = (version?: string, signal?: AbortSignal) => api<Catalog>('/catalog' + (version ? '?version=' + encodeURIComponent(version) : ''), { signal })
export const createSession = (version: string, csrf?: string | null) => api<components['schemas']['SessionCreated']>('/sessions', { method: 'POST', headers: csrf ? { 'X-CSRF-Token': csrf } : {}, body: JSON.stringify({ catalogVersion: version }) })
export const getSession = (ref: SessionRef, signal?: AbortSignal) => api<Session>(`/sessions/${ref.id}`, { headers: headers(ref, null), signal })
export const saveContext = (ref: SessionRef, session: Session, context: Context, csrf?: string | null) => api<Session>(`/sessions/${ref.id}/context`, { method: 'PUT', headers: headers(ref, csrf), body: JSON.stringify({ context, expectedRevision: session.revision }) })
export const getQuestions = (ref: SessionRef, signal?: AbortSignal) => api<Questions>(`/sessions/${ref.id}/questions`, { headers: headers(ref, null), signal })
export const evaluate = (ref: SessionRef, pending: Pending, csrf?: string | null) => api<Guidance>(`/sessions/${ref.id}/evaluations`, { method: 'POST', headers: headers(ref, csrf), body: JSON.stringify(pending), signal: AbortSignal.timeout(15000) })
export const requestState = (ref: SessionRef, pending: Pending) => api<RequestState>(`/sessions/${ref.id}/requests/${pending.requestId}`, { headers: headers(ref, null), signal: AbortSignal.timeout(15000) })
export const getResult = (ref: SessionRef, id: string, signal?: AbortSignal) => api<Guidance>(`/sessions/${ref.id}/results/${id}`, { headers: headers(ref, null), signal })
export const getHistory = (cursor?: string | null, signal?: AbortSignal) => api<History>('/me/results' + (cursor ? '?cursor=' + encodeURIComponent(cursor) : ''), { signal })
export const getHistoryResult = (id: string, signal?: AbortSignal) => api<Guidance>(`/me/results/${id}`, { signal })
export const deleteResult = (id: string, csrf: string) => api<void>(`/me/results/${id}`, { method: 'DELETE', headers: { 'X-CSRF-Token': csrf } })
export const deleteQuestions = (csrf: string) => api<void>('/me/question-records', { method: 'DELETE', headers: { 'X-CSRF-Token': csrf } })
export const endSession = (ref: SessionRef, csrf?: string | null, erase = false) => api<void>(`/sessions/${ref.id}?eraseRecords=${erase}`, { method: 'DELETE', headers: headers(ref, csrf) })
