import type { components } from '../../api/generated/schema'

export type Session = components['schemas']['Session']
export type Context = components['schemas']['Context']
export type Catalog = components['schemas']['Catalog']
export type Guidance = components['schemas']['GuidanceResult']
export type SessionRef = { id: string; token: string | null; mode: 'GUEST' | 'MEMBER'; purpose?: 'SURVEY' | 'CHAT' }
export type Pending = { requestId: string; expectedRevision: number }
const GUEST_KEY = 'guest-session'
const MEMBER_KEY = 'member-session-id'
const CHAT_KEY = 'member-chat-session-id'
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i
let epoch = 0
const listeners = new Set<() => void>()

export const identityEpoch = () => epoch
export function subscribe(listener: () => void) { listeners.add(listener); return () => { listeners.delete(listener) } }
function changed() { for (const listener of listeners) listener() }

export function storedReference(member: boolean, purpose: 'SURVEY' | 'CHAT' = 'SURVEY'): string | null {
  if (typeof sessionStorage === 'undefined') return null
  const raw = sessionStorage.getItem(purpose === 'CHAT' ? CHAT_KEY : member ? MEMBER_KEY : GUEST_KEY)
  if (!raw) return null
  if (member) return UUID.test(raw) ? raw : null
  try {
    const value = JSON.parse(raw) as { id?: string; token?: string; expiresAt?: string }
    return value.id && UUID.test(value.id) && /^[a-zA-Z0-9_-]{43}$/.test(value.token ?? '') && Date.parse(value.expiresAt ?? '') > Date.now() ? raw : null
  } catch { return null }
}

export function referenceFrom(raw: string | null, member: boolean, purpose: 'SURVEY' | 'CHAT' = 'SURVEY'): SessionRef | null {
  if (!raw) return null
  return member ? { id: raw, token: null, mode: 'MEMBER', purpose } : { ...JSON.parse(raw), mode: 'GUEST', purpose }
}

export function storeSession(session: Session, token: string | null) {
  if (session.accessMode === 'GUEST' && token) sessionStorage.setItem(GUEST_KEY, JSON.stringify({ id: session.id, token, expiresAt: session.expiresAt }))
  else sessionStorage.setItem(session.purpose === 'CHAT' ? CHAT_KEY : MEMBER_KEY, session.id)
  changed()
}

export function clearSession(reference: SessionRef) {
  const key = reference.purpose === 'CHAT' ? CHAT_KEY : reference.mode === 'MEMBER' ? MEMBER_KEY : GUEST_KEY
  const raw = sessionStorage.getItem(key)
  try { if ((reference.mode === 'MEMBER' ? raw : JSON.parse(raw ?? 'null')?.id) === reference.id) sessionStorage.removeItem(key) } catch { /* Invalid recovery data cannot identify this session. */ }
  clearPending(reference.id)
  sessionStorage.removeItem('chat-pending-' + reference.id)
  changed()
}

export function resetSurveyIdentity() {
  epoch++
  sessionStorage.removeItem(MEMBER_KEY)
  sessionStorage.removeItem(CHAT_KEY)
  sessionStorage.removeItem(GUEST_KEY)
  for (let index = sessionStorage.length - 1; index >= 0; index--) {
    const key = sessionStorage.key(index)
    if (key?.startsWith('survey-pending-') || key?.startsWith('chat-pending-')) sessionStorage.removeItem(key)
  }
  changed()
}

export function readPending(sessionId: string): Pending | null {
  try {
    const value = JSON.parse(sessionStorage.getItem('survey-pending-' + sessionId) ?? 'null') as Pending | null
    return value && UUID.test(value.requestId) && Number.isInteger(value.expectedRevision) && value.expectedRevision >= 0 ? value : null
  } catch { return null }
}
export function storePending(id: string, pending: Pending) { sessionStorage.setItem('survey-pending-' + id, JSON.stringify(pending)) }
export function clearPending(id: string) { sessionStorage.removeItem('survey-pending-' + id) }
