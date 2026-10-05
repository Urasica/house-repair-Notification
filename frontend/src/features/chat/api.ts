import type { components } from '../../api/generated/schema'
import { api } from '../../api/client'
import type { Pending, SessionRef } from '../survey/storage'
import { headers } from '../survey/api'

export type ChatResponse = components['schemas']['ChatResponse']
export type ChatHistory = components['schemas']['ChatHistory']
export const chatHistory = (ref: SessionRef, cursor: string | null, signal?: AbortSignal) => api<ChatHistory>(`/sessions/${ref.id}/chat/messages` + (cursor ? '?cursor=' + encodeURIComponent(cursor) : ''), { signal })
export const sendChat = (ref: SessionRef, pending: Pending, content: string, csrf?: string | null) => api<ChatResponse>(`/sessions/${ref.id}/chat/messages`, { method: 'POST', headers: headers(ref, csrf), body: JSON.stringify({ ...pending, content }), signal: AbortSignal.timeout(30000) })

export function pendingChat(id: string): Pending | null {
  try {
    const value = JSON.parse(sessionStorage.getItem('chat-pending-' + id) ?? 'null') as Pending | null
    return value && /^[a-f0-9-]{36}$/i.test(value.requestId) && Number.isInteger(value.expectedRevision) && value.expectedRevision >= 0 ? value : null
  } catch { return null }
}
export function saveChatPending(id: string, value: Pending | null) {
  if (value) sessionStorage.setItem('chat-pending-' + id, JSON.stringify(value))
  else sessionStorage.removeItem('chat-pending-' + id)
}
