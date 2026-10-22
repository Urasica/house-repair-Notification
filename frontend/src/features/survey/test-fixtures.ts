// Imported only by tests. Never publish or use these values as screen fallback data.
import type { AuthState } from '../auth/api'
import type { Catalog, Guidance, Session } from './storage'
import type { Questions } from './api'

export const sessionId = '00000000-0000-4000-8000-000000000001'
export const resultId = '00000000-0000-4000-8000-000000000002'
export const testToken = 't'.repeat(43)
export const member: AuthState = { user: { id: '00000000-0000-4000-8000-000000000003', email: 'test@example.com', createdAt: '2026-10-03T00:00:00Z' }, csrfToken: 'test-only-csrf' }
export const catalog: Catalog = {
  version: 'test-only-v1', publishedAt: '2026-10-03T00:00:00Z',
  housingTypes: [
    { id: 'LH_CONSTRUCTION_RENTAL', label: '시험용 건설임대', supported: true },
    { id: 'LH_RENTAL_BEFORE_SALE', label: '시험용 분양전환 임대', supported: true },
    { id: 'SOLD_OR_PRIVATE', label: '시험용 민간 주택', supported: false },
    { id: 'OTHER', label: '시험용 기타', supported: false }, { id: 'UNKNOWN', label: '모름', supported: false },
  ],
  rooms: [{ id: 'test-room', label: '시험용 공간' }, { id: 'test-room2', label: '시험용 다른 공간' }],
  facilities: [{ id: 'test-facility', label: '시험용 시설물', roomIds: ['test-room'] }, { id: 'test-facility2', label: '시험용 다른 시설물', roomIds: ['test-room2'] }],
  symptoms: [{ id: 'test-symptom', label: '시험용 증상', facilityIds: ['test-facility'] }, { id: 'test-symptom2', label: '시험용 다른 증상', facilityIds: ['test-facility2'] }],
}
export function sessionFixture(isMember = false): Session {
  return { id: sessionId, purpose: 'SURVEY', accessMode: isMember ? 'MEMBER' : 'GUEST', catalogVersion: catalog.version, context: { description: '', answers: {} }, revision: 0, currentResultId: null, knowledgeReleaseId: null, createdAt: new Date().toISOString(), expiresAt: new Date(Date.now() + 86400000).toISOString() }
}
export function filledSession(isMember = false): Session {
  return { ...sessionFixture(isMember), revision: 1, context: { housingType: 'LH_CONSTRUCTION_RENTAL', roomId: 'test-room', facilityId: 'test-facility', symptomId: 'test-symptom', description: '', answers: { 'test-question': 'UNKNOWN' } } }
}
export function questionsFixture(session: Session): Questions {
  const questions: Questions['questions'] = session.context.symptomId ? [{ questionId: 'test-question', label: '시험용 확인 질문', required: true, type: 'singleChoice', options: [{ value: 'TEST', label: '시험용 일반 선택' }, { value: 'RISK', label: '시험용 위험 선택' }, { value: 'UNKNOWN', label: '모름' }], interruptValues: ['RISK'] }] : []
  if (session.context.answers?.['test-question'] === 'TEST') questions.push({ questionId: 'test-follow-up', label: '시험용 분기 질문', required: true, type: 'singleChoice', options: [{ value: 'YES', label: '시험용 후속 답' }, { value: 'UNKNOWN', label: '모름' }] })
  return { catalogVersion: session.catalogVersion, revision: session.revision, questions }
}
export function resultFixture(session: Session): Guidance {
  return { id: resultId, sessionId: session.id, status: session.context.answers?.['test-question'] === 'RISK' ? 'SAFETY_PRIORITY' : 'NEED_CONFIRMATION', reasonCodes: ['NO_APPLICABLE_SOURCE'], summary: { housingLabel: '시험용 주택', roomLabel: '시험용 공간', facilityLabel: '시험용 시설물', symptomLabel: '시험용 증상', description: session.context.description, answerLabels: Object.values(session.context.answers ?? {}) }, guidance: ['관련 정보가 부족하여 안내할 수 없어요.'], checks: [], followUpQuestions: [], citations: [], contactDraft: '담당 기관에 직접 확인해 주세요.', disclaimer: '실제 보수 여부는 담당 기관 확인이 필요해요.', catalogVersion: session.catalogVersion, knowledgeReleaseId: null, contextRevision: session.revision, engineVersion: 'test-only', isCurrent: true, savedToHistory: session.accessMode === 'MEMBER', generatedAt: new Date().toISOString(), retainedUntil: new Date(Date.now() + 86400000 * 8).toISOString() }
}
