// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from '../../App'
import { AUTH_KEY, anonymous } from '../auth/state'
import { resetSurveyIdentity, storeSession } from '../survey/storage'
import { catalog, filledSession, member, resultFixture, sessionFixture } from '../survey/test-fixtures'
import { pendingChat, saveChatPending } from './api'
import type { ChatResponse } from './api'

let root: Root, host: HTMLDivElement, client: QueryClient
let current = filledSession(true)
let replies: ChatResponse[]
let lost: boolean, held: boolean, signedIn: boolean
let release: (response: Response) => void
const json = (value: unknown) => new Response(JSON.stringify(value), { status: 200 })
let sent: Record<string, unknown>[]
let state: 'COMPLETED' | 'PROCESSING' | 'DELETED' | 'FAILED'
let calls: string[]
let exists: boolean, deleteFailure: boolean, deleteLost: boolean, createFailure: boolean
let createdBodies: Record<string, unknown>[]
const failure = (status: number, code: string) => new Response(JSON.stringify({ error: { code, message: '시험 오류' } }), { status })

function answer(requestId: string, content = '제10조 내용') : ChatResponse {
  return { requestId, contextRevision: current.revision, answerMode: 'CLARIFY', status: 'NEED_MORE_INFO',
    userMessage: { id: crypto.randomUUID(), requestId, role: 'USER', content, citations: [], createdAt: new Date().toISOString(), isCurrent: true },
    assistantMessage: { id: crypto.randomUUID(), requestId, role: 'ASSISTANT', content: '선택한 내용을 확인해 주세요.', citations: [], createdAt: new Date().toISOString(), isCurrent: true },
    followUpQuestions: ['설문 답을 확인해 주세요.'], disclaimer: '실제 보수 여부는 담당 기관 확인이 필요해요.', isCurrent: true }
}
beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  sessionStorage.clear(); resetSurveyIdentity(); current = { ...filledSession(true), purpose: 'CHAT' }
  signedIn = true; replies = []; sent = []; calls = []; lost = false; held = false; state = 'COMPLETED'; release = () => {}
  exists = true; deleteFailure = false; deleteLost = false; createFailure = false; createdBodies = []
  vi.stubGlobal('fetch', vi.fn(async (url: string, options: RequestInit = {}) => {
    const path = url.replace('/api/v1', ''); calls.push(path)
    if (path === '/auth/logout') { signedIn = false; return new Response(null, { status: 204 }) }
    if (path === '/auth/me') return json(signedIn ? member : anonymous)
    if (path.startsWith('/catalog')) return json(catalog)
    if (path.startsWith('/me/results')) return json({ items: [resultFixture(filledSession(true))], nextCursor: null })
    if (path.endsWith('/chat/survey-context')) {
      const body = JSON.parse(options.body as string) as { resultId: string; expectedRevision: number }
      expect(body).toEqual({ resultId: resultFixture(current).id, expectedRevision: current.revision })
      current = { ...current, revision: current.revision + 1, context: filledSession(true).context }
      expect(options.headers).toMatchObject({ 'X-CSRF-Token': member.csrfToken })
      return json(current)
    }
    if (path === '/sessions' && options.method === 'POST') {
      createdBodies.push(JSON.parse(options.body as string) as Record<string, unknown>)
      if (createFailure) return failure(503, 'SERVICE_UNAVAILABLE')
      current = { ...sessionFixture(true), id: crypto.randomUUID(), purpose: 'CHAT' }
      exists = true; replies = []
      return json({ session: current, sessionToken: null })
    }
    if (path === '/sessions/' + current.id + '?eraseRecords=false' && options.method === 'DELETE') {
      if (deleteFailure) return failure(409, 'SESSION_BUSY')
      exists = false; replies = []
      if (deleteLost) throw new TypeError('delete response lost')
      return new Response(null, { status: 204 })
    }
    if (path === '/sessions/' + current.id) return exists ? json(current) : failure(404, 'NOT_FOUND')
    if (path.endsWith('/chat/messages') && options.method === 'POST') {
      const body = JSON.parse(options.body as string) as Record<string, unknown>; sent.push(body)
      const result = answer(body.requestId as string, body.content as string); replies = [result]
      if (lost) throw new TypeError('response lost')
      if (held) return new Promise<Response>(resolve => { release = resolve })
      return json(result)
    }
    if (path.includes('/chat/messages')) return json({ items: replies, nextCursor: null })
    if (path.includes('/requests/')) return json({ requestId: path.split('/').at(-1), kind: 'CHAT', state, response: state === 'COMPLETED' ? replies[0] : null, retryAfterMs: 5 })
    throw new Error('Unhandled endpoint ' + path)
  }))
  host = document.createElement('div'); document.body.append(host); root = createRoot(host)
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } })
  storeSession(current, null)
})
afterEach(async () => { await act(async () => root.unmount()); client.clear(); host.remove(); sessionStorage.clear(); vi.unstubAllGlobals() })
async function render() { await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/chat']}><App /></MemoryRouter></QueryClientProvider>)) }
async function until(check: () => void) { await vi.waitFor(async () => { await act(async () => { await Promise.resolve() }); check() }) }
function button(text: string) { return [...host.querySelectorAll('button')].find(item => item.textContent === text)! }
async function enter(text: string) {
  const input = host.querySelector<HTMLTextAreaElement>('#chat-input')!
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value')!.set!.call(input, text)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}
async function submit() { await act(async () => host.querySelector('form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))) }

it('sends once, restores complete display metadata and escapes user content', async () => {
  await render(); await until(() => expect(host.querySelector('#chat-input')).not.toBeNull())
  await enter('<script>private@example.com</script> 제10조 내용')
  await submit()
  await until(() => expect(host.textContent).toContain('대화가 저장됐어요.'))
  expect(sent).toHaveLength(1); expect(host.querySelector('script')).toBeNull()
  expect(host.textContent).toContain('설문 답을 확인해 주세요.')
  expect(host.textContent).toContain('추가 확인')
  expect(pendingChat(current.id)).toBeNull()
  expect(JSON.stringify(sessionStorage)).not.toContain('private@example.com')
})

it('imports only after choosing a saved survey and explicitly requesting it', async () => {
  current.context = { description: '', answers: {} }
  await render(); await until(() => expect(host.querySelector('#chat-input')).not.toBeNull())
  expect(calls.some(path => path.includes('/me/results') || path.includes('/survey-context'))).toBe(false)
  await act(async () => button('이전 설문 불러오기').click())
  await until(() => expect(host.querySelectorAll('#import-survey option')).toHaveLength(2))
  expect(calls.some(path => path.includes('/survey-context'))).toBe(false)
  const select = host.querySelector<HTMLSelectElement>('#import-survey')!
  await act(async () => { select.value = resultFixture(current).id; select.dispatchEvent(new Event('change', { bubbles: true })) })
  await act(async () => button('선택한 설문 불러오기').click())
  await until(() => expect(host.textContent).toContain('선택한 설문을 불러왔어요'))
  expect(current.context.answers).toEqual({ 'test-question': 'UNKNOWN' })
  expect(host.textContent).toContain('설문 답변 1개')
  expect(sent).toHaveLength(0)
  await enter('이 경우 무엇을 확인하나요?'); await submit()
  await until(() => expect(sent).toHaveLength(1))
  expect(sent[0].expectedRevision).toBe(current.revision)
})

it('recovers a lost response with its original request and no duplicate POST', async () => {
  lost = true
  await render(); await until(() => expect(host.querySelector('#chat-input')).not.toBeNull())
  await enter('제10조 내용을 알려 주세요'); await submit()
  await until(() => expect(button('전송 결과 확인').disabled).toBe(false))
  const pending = pendingChat(current.id)
  expect(pending?.requestId).toBe(sent[0].requestId)
  expect(sessionStorage.getItem('chat-pending-' + current.id)).not.toContain('content')
  await act(async () => button('전송 결과 확인').click())
  await until(() => expect(pendingChat(current.id)).toBeNull())
  expect(sent).toHaveLength(1)
})

it('restores pending IDs after reload and respects deleted requests without resending', async () => {
  state = 'DELETED'
  saveChatPending(current.id, { requestId: crypto.randomUUID(), expectedRevision: current.revision })
  await render(); await until(() => expect(button('전송 결과 확인')).toBeDefined())
  expect(button('같은 요청 다시 보내기')).toBeUndefined()
  await act(async () => button('전송 결과 확인').click())
  await until(() => expect(host.textContent).toContain('완료되지 않았거나 삭제된 요청'))
  expect(sent).toHaveLength(0); expect(pendingChat(current.id)).toBeNull()
})

it('history GET restores clarification and stale labels without generation', async () => {
  const result = answer(crypto.randomUUID()); result.isCurrent = false; replies = [result]
  await render(); await until(() => expect(host.textContent).toContain('이전 입력이나 기준의 답변'))
  expect(host.textContent).toContain('설문 답을 확인해 주세요.')
  expect(sent).toHaveLength(0)
})
it('restores hypothetical repair examples with the saved answer and keeps clarification visible', async () => {
  replies = [{ ...answer(crypto.randomUUID()), referenceExamples: ['연결 부위의 보수를 검토할 수 있어요.'] }]
  await render()
  await until(() => expect(host.querySelector('.repair-examples')).not.toBeNull())
  expect(host.textContent).toContain('가상 예시')
  expect(host.querySelectorAll('.repair-examples li')).toHaveLength(1)
  expect(host.textContent).toContain('설문 답을 확인해 주세요.')
  expect(sent).toHaveLength(0)
})

it('ignores late completion after logout and clears chat recovery data', async () => {
  held = true
  await render(); await until(() => expect(host.querySelector('#chat-input')).not.toBeNull())
  await enter('제10조 설명'); await submit()
  expect(pendingChat(current.id)).not.toBeNull()
  await act(async () => button('로그아웃').click())
  await until(() => expect(sessionStorage.length).toBe(0))
  await act(async () => release(json(replies[0])))
  expect(client.getQueryData(AUTH_KEY)).toEqual(anonymous)
  expect(pendingChat(current.id)).toBeNull()
  expect(client.getQueriesData({ queryKey: ['chat'] })).toHaveLength(0)
})

it('starts a separate empty chat when a member has only a survey session', async () => {
  sessionStorage.clear()
  const survey = filledSession(true)
  storeSession(survey, null)
  await render(); await until(() => expect(host.querySelector('#chat-input')).not.toBeNull())
  expect(createdBodies).toEqual([{ catalogVersion: catalog.version, purpose: 'CHAT' }])
  expect(current.context.answers).toEqual({})
  expect(sessionStorage.getItem('member-session-id')).toBe(survey.id)
  expect(sessionStorage.getItem('member-chat-session-id')).not.toBe(survey.id)
  expect(host.querySelector('a[href="/survey"]')).toBeNull()
  expect(host.querySelector('a[href="/select"]')).toBeNull()
})

it('cancels reset, then resets only chat and preserves the independent survey', async () => {
  const survey = { ...filledSession(true), id: crypto.randomUUID() }
  storeSession(survey, null)
  const surveyKey = ['session', survey.id, member.user!.id, 'SURVEY']
  client.setQueryData(surveyKey, survey)
  replies = [answer(crypto.randomUUID(), '지울 질문')]
  const old = current.id
  await render(); await until(() => expect(host.textContent).toContain('지울 질문'))
  await enter('입력 중인 질문')
  await act(async () => button('대화 초기화').click())
  await act(async () => button('취소').click())
  expect((host.querySelector('#chat-input') as HTMLTextAreaElement).value).toBe('입력 중인 질문')
  expect(calls.some(path => path.includes('eraseRecords'))).toBe(false)
  await act(async () => button('대화 초기화').click())
  await act(async () => button('초기화 확인').click())
  await until(() => expect(current.id).not.toBe(old))
  await until(() => expect(host.querySelector('#chat-input')).not.toBeNull())
  expect(host.textContent).not.toContain('지울 질문')
  expect((host.querySelector('#chat-input') as HTMLTextAreaElement).value).toBe('')
  expect(sessionStorage.getItem('member-session-id')).toBe(survey.id)
  expect(sessionStorage.getItem('member-chat-session-id')).toBe(current.id)
  expect(client.getQueryData(AUTH_KEY)).toEqual(member)
  expect(client.getQueryData(surveyKey)).toEqual(survey)
  expect(client.getQueriesData({ queryKey: ['chat', old] })).toHaveLength(0)
  expect(client.getQueriesData({ queryKey: ['chat-session', old] })).toHaveLength(0)
  expect(current.revision).toBe(0)
})

it('keeps the old conversation when reset is busy or deletion fails', async () => {
  deleteFailure = true; replies = [answer(crypto.randomUUID(), '유지할 질문')]
  const old = current.id
  await render(); await until(() => expect(host.textContent).toContain('유지할 질문'))
  await act(async () => button('대화 초기화').click())
  await act(async () => button('초기화 확인').click())
  await until(() => expect(host.textContent).toContain('시험 오류'))
  expect(sessionStorage.getItem('member-chat-session-id')).toBe(old)
  expect(host.textContent).toContain('유지할 질문')
  expect(createdBodies).toHaveLength(0)
})

it('recovers a lost deletion response and retries only creation after creation failure', async () => {
  deleteLost = true; createFailure = true
  const old = current.id
  await render(); await until(() => expect(button('대화 초기화')).toBeDefined())
  await act(async () => button('대화 초기화').click())
  await act(async () => button('초기화 확인').click())
  await until(() => expect(button('새 대화 다시 시작')).toBeDefined())
  expect(sessionStorage.getItem('member-chat-session-id')).toBeNull()
  createFailure = false
  await act(async () => button('새 대화 다시 시작').click())
  await until(() => expect(host.querySelector('#chat-input')).not.toBeNull())
  expect(current.id).not.toBe(old)
  expect(calls.filter(path => path.includes('eraseRecords'))).toHaveLength(1)
})

it('disables reset while sending and shows evidence in the site without opening a link', async () => {
  const result = answer(crypto.randomUUID())
  result.assistantMessage.citations = [{ chunkId: crypto.randomUUID(), documentVersionId: crypto.randomUUID(), kind: 'LAW_CRITERIA', use: 'APPLICABLE', title: '검토 자료', locator: '제10조', url: 'https://example.invalid/source', excerpt: '원문의 적용 조건과 단서', effectiveDate: '2026-01-01', reviewedAt: new Date().toISOString(), reviewUntil: new Date(Date.now() + 86400000).toISOString() }]
  replies = [result]
  await render(); await until(() => expect(host.querySelector('details')).not.toBeNull())
  expect(host.querySelector('details')?.textContent).toContain('원문의 적용 조건과 단서')
  expect(host.querySelector('details summary')?.textContent).toContain('제10조')
  held = true
  await enter('추가 질문'); await submit()
  expect(button('대화 초기화').disabled).toBe(true)
  await act(async () => release(json(replies[0])))
})
