// @vitest-environment jsdom
import { afterEach, expect, it } from 'vitest'
import { clearSession, identityEpoch, readPending, referenceFrom, resetSurveyIdentity, storePending, storeSession, storedReference } from './storage'
import { filledSession, sessionFixture, sessionId, testToken } from './test-fixtures'

afterEach(() => sessionStorage.clear())
it('stores only the guest recovery token, expiry and id, with no raw context or result', () => {
  const session = filledSession()
  session.context.description = 'test-private-input'
  storeSession(session, testToken)
  expect(referenceFrom(storedReference(false), false)).toMatchObject({ id: sessionId, token: testToken, mode: 'GUEST' })
  expect(JSON.stringify(sessionStorage)).not.toContain('test-private-input')
  expect(JSON.stringify(sessionStorage)).not.toContain('test-symptom')
})
it('stores only a member consultation id and rejects expired or malformed guest credentials', () => {
  storeSession(sessionFixture(true), null)
  expect(sessionStorage.getItem('member-session-id')).toBe(sessionId)
  expect(referenceFrom(storedReference(true), true)?.token).toBeNull()
  storeSession({ ...sessionFixture(), expiresAt: '2000-01-01T00:00:00Z' }, testToken)
  expect(storedReference(false)).toBeNull()
  sessionStorage.setItem('guest-session', '{bad-json')
  expect(storedReference(false)).toBeNull()
})
it('identity changes erase both consultations and every pending request; ending one erases its pending id', () => {
  const session = sessionFixture()
  storeSession(session, testToken)
  storeSession(sessionFixture(true), null)
  storePending(session.id, { requestId: crypto.randomUUID(), expectedRevision: 4 })
  expect(readPending(session.id)?.expectedRevision).toBe(4)
  clearSession({ id: session.id, token: testToken, mode: 'GUEST' })
  expect(readPending(session.id)).toBeNull()
  storeSession(session, testToken)
  storePending(session.id, { requestId: crypto.randomUUID(), expectedRevision: 0 })
  const before = identityEpoch()
  resetSurveyIdentity()
  expect(identityEpoch()).toBeGreaterThan(before)
  expect(sessionStorage.length).toBe(0)
})
