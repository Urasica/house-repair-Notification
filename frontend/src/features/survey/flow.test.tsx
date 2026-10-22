// @vitest-environment jsdom
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import type { Root } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { Mock } from 'vitest'
import App from '../../App'
import { AUTH_KEY, anonymous, replaceAuth } from '../auth/state'
import { readPending, resetSurveyIdentity, storePending, storeSession } from './storage'
import type { Context, Guidance, Pending, Session } from './storage'
import { catalog, filledSession, member, questionsFixture, resultFixture, resultId, sessionFixture, sessionId, testToken } from './test-fixtures'

let root: Root
let host: HTMLDivElement
let client: QueryClient
let current: Session
let result: Guidance
let isMember: boolean
let missingCatalog: boolean
let evaluationMode: 'OK' | 'LOST' | 'WAIT'
let recoveryState: 'PROCESSING' | 'COMPLETED' | 'FAILED' | 'DELETED'
let saveConflict: boolean
let release: (response: Response) => void
let sent: Pending[]
let fetcher: Mock<(url: string, options?: RequestInit) => Promise<Response>>
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status })
const failure = (code: string, status = 409) => json({ error: { code, message: '시험 오류: ' + code, details: {}, traceId: crypto.randomUUID() } }, status)

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  vi.spyOn(window, 'scrollTo').mockImplementation(() => {})
  sessionStorage.clear(); resetSurveyIdentity()
  current = sessionFixture(); result = resultFixture(current)
  isMember = false; missingCatalog = false; evaluationMode = 'OK'; recoveryState = 'COMPLETED'; saveConflict = false; sent = []
  release = () => {}
  fetcher = vi.fn(async (url: string, options: RequestInit = {}) => {
    const path = url.replace('/api/v1', '')
    const method = options.method ?? 'GET'
    if (path === '/auth/me') return json(isMember ? member : anonymous)
    if (path === '/auth/logout') { isMember = false; return new Response(null, { status: 204 }) }
    if (path.startsWith('/catalog')) return missingCatalog ? failure('CATALOG_NOT_READY', 503) : json(catalog)
    if (path === '/sessions' && method === 'POST') { current = sessionFixture(isMember); return json({ session: current, sessionToken: isMember ? null : testToken }, 201) }
    if (path === '/sessions/' + sessionId) return json(current)
    if (path.endsWith('/context')) {
      if (saveConflict) return failure('CONTEXT_CONFLICT')
      const body = JSON.parse(options.body as string) as { context: Context; expectedRevision: number }
      if (body.expectedRevision !== current.revision) return failure('CONTEXT_CONFLICT')
      const context = body.context
      if (context.answers?.['test-question'] !== 'TEST') delete context.answers?.['test-follow-up']
      current = { ...current, context, revision: current.revision + 1, currentResultId: null }
      return json(current)
    }
    if (path.endsWith('/questions')) return json(questionsFixture(current))
    if (path.endsWith('/evaluations')) {
      sent.push(JSON.parse(options.body as string) as Pending)
      result = resultFixture(current); current = { ...current, currentResultId: result.id }
      if (evaluationMode === 'LOST') throw new TypeError('test response lost')
      if (evaluationMode === 'WAIT') return new Promise<Response>(resolve => { release = resolve })
      return json(result, 201)
    }
    if (path.includes('/requests/')) return json({ requestId: path.split('/').at(-1), kind: 'SURVEY', state: recoveryState, response: recoveryState === 'COMPLETED' ? result : null, retryAfterMs: recoveryState === 'PROCESSING' ? 10 : null })
    if (method === 'DELETE') return new Response(null, { status: 204 })
    if (path.startsWith('/me/results?')) return json({ items: [{ ...result, id: '00000000-0000-4000-8000-000000000004' }], nextCursor: null })
    if (path === '/me/results') return json({ items: [{ ...result }], nextCursor: 'test-cursor' })
    if (path.includes('/results/')) return json(result)
    throw new Error('Unhandled test endpoint: ' + method + ' ' + path)
  })
  vi.stubGlobal('fetch', fetcher)
  host = document.createElement('div'); document.body.append(host)
  root = createRoot(host)
  client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity }, mutations: { retry: false } } })
})
afterEach(async () => {
  await act(async () => root.unmount())
  client.clear(); host.remove(); sessionStorage.clear(); vi.unstubAllGlobals()
})
async function render(path = '/', existing = false) {
  if (existing) storeSession(current, isMember ? null : testToken)
  await act(async () => root.render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><App /></MemoryRouter></QueryClientProvider>))
}
async function until(assertion: () => void) { await vi.waitFor(async () => { await act(async () => { await Promise.resolve() }); assertion() }) }
function button(label: string) { const found = [...host.querySelectorAll('button')].find(item => item.textContent === label); if (!found) throw new Error('Button missing: ' + label); return found }
async function click(element: HTMLElement) { await act(async () => element.click()) }
async function choose(id: string, value: string) {
  const element = host.querySelector<HTMLSelectElement>('#' + id)!
  await act(async () => { element.value = value; element.dispatchEvent(new Event('change', { bubbles: true })) })
}
async function radio(value: string) { await click(host.querySelector<HTMLInputElement>('input[type=radio][value="' + value + '"]')!) }
const count = (suffix: string, method?: string) => fetcher.mock.calls.filter(([url, opts]) => String(url).includes(suffix) && (!method || (opts as RequestInit)?.method === method)).length

it('keeps the unpublished catalog empty and never starts a session', async () => {
  missingCatalog = true
  await render()
  await until(() => expect(host.textContent).toContain('안내 서비스를 준비하고 있어요'))
  expect(button('설문 준비 중').disabled).toBe(true)
  expect(host.textContent).not.toContain('시험용')
  expect(count('/sessions', 'POST')).toBe(0)
})
it.each([false, true])('completes selection, branch, evaluation and result with scoped caches (member=%s)', async memberMode => {
  isMember = memberMode
  const userId = memberMode ? member.user!.id : null
  await render()
  await until(() => expect(button('새 설문 시작').disabled).toBe(false))
  await click(button('새 설문 시작'))
  await until(() => expect(host.querySelector('#room')).not.toBeNull())
  expect(client.getQueryData(['session', sessionId, userId, 'SURVEY'])).toEqual(current)
  expect(host.querySelector('textarea')?.maxLength).toBe(1000)
  await radio('LH_CONSTRUCTION_RENTAL')
  await choose('room', 'test-room'); await choose('facility', 'test-facility'); await choose('symptom', 'test-symptom')
  await click(button('저장하고 설문으로'))
  await until(() => expect(host.textContent).toContain('시험용 확인 질문'))
  expect(host.querySelector('fieldset legend')?.textContent).toContain('필수 확인')
  await radio('TEST')
  await until(() => expect(host.textContent).toContain('시험용 분기 질문'))
  await radio('YES')
  await until(() => expect(button('안내 결과 확인').disabled).toBe(false))
  expect(client.getQueryData(['session', sessionId, userId, 'SURVEY'])).toEqual(current)
  expect(client.getQueryData(['questions', sessionId, current.revision, userId, 'SURVEY'])).toEqual(questionsFixture(current))
  const evaluate = button('안내 결과 확인')
  await act(async () => { evaluate.click(); evaluate.click() })
  await until(() => expect(host.textContent).toContain(memberMode ? '계정의 이전 결과에 저장됐어요' : '현재 익명 상담에 저장됐어요'))
  expect(client.getQueryData(['result', sessionId, resultId, userId, 'SURVEY'])).toEqual(result)
  expect(sent).toHaveLength(1)
  expect(sent[0].expectedRevision).toBe(3)
  expect(readPending(sessionId)).toBeNull()
  expect(host.textContent).toContain('담당 기관에 직접 확인해 주세요.')
  expect(host.querySelector('a[href^="tel:"]')).toBeNull()
  expect(JSON.stringify(sessionStorage)).not.toContain('시험용')
  const evaluationCall = fetcher.mock.calls.find(([url]) => String(url).endsWith('/evaluations'))!
  expect((evaluationCall[1] as RequestInit).headers).toMatchObject(memberMode ? { 'X-CSRF-Token': member.csrfToken } : { Authorization: 'Bearer ' + testToken })
})
it('keeps an unanswered required question on the survey and accepts UNKNOWN as an answer', async () => {
  current = filledSession(); current.context.answers = {}
  await render('/survey', true)
  await until(() => expect(button('안내 결과 확인').disabled).toBe(false))
  await click(button('안내 결과 확인'))
  expect(sent).toHaveLength(0)
  expect(host.textContent).toContain('답을 골라 주세요')
  expect(document.activeElement?.getAttribute('name')).toBe('test-question')
  await radio('UNKNOWN')
  await until(() => expect(button('안내 결과 확인').disabled).toBe(false))
  await click(button('안내 결과 확인'))
  await until(() => expect(sent).toHaveLength(1))
})
it('returns a missing-input result directly to its unanswered survey question', async () => {
  current = filledSession(); current.context.answers = {}
  result = { ...resultFixture(current), status: 'NEED_MORE_INFO', reasonCodes: ['MISSING_INPUT'] }
  await render('/result/' + resultId, true)
  await until(() => expect(host.querySelector('a[href="/survey"]')).not.toBeNull())
  await click(host.querySelector<HTMLAnchorElement>('a[href="/survey"]')!)
  await until(() => expect(host.textContent).toContain('답을 골라 주세요'))
  expect(document.activeElement?.getAttribute('name')).toBe('test-question')
})
it('explains how to check an unknown housing type before continuing', async () => {
  current = filledSession(); current.context.housingType = 'UNKNOWN'
  await render('/select', true)
  await until(() => expect(host.textContent).toContain('임대차계약서나 입주 안내문'))
})
it.each([true, false])('copies a contextual inquiry or provides manual copy recovery (clipboard=%s)', async available => {
  current = filledSession(); current.context.description = '비공개 추가 설명'
  result = resultFixture(current)
  const writeText = vi.fn().mockImplementation(() => available ? Promise.resolve() : Promise.reject(new Error('denied')))
  vi.stubGlobal('navigator', { clipboard: { writeText } })
  await render('/result/' + resultId, true)
  await until(() => expect(host.textContent).toContain('지금 할 일'))
  const article = host.querySelector('article')!
  expect(article.querySelector('h2')?.textContent).toBe('지금 할 일')
  expect(article.querySelector('details')?.open).toBe(false)
  await click(button('문의 내용 복사'))
  await until(() => expect(writeText).toHaveBeenCalledTimes(1))
  expect(writeText.mock.calls[0][0]).toContain('위치: 시험용 공간 · 시험용 시설물')
  expect(writeText.mock.calls[0][0]).toContain('증상: 시험용 증상')
  expect(writeText.mock.calls[0][0]).not.toContain('비공개 추가 설명')
  if (available) expect(host.textContent).toContain('문의 내용을 복사했어요')
  else expect(host.querySelector<HTMLTextAreaElement>('[aria-label="복사할 문의 내용"]')?.readOnly).toBe(true)
})
it('invalidates descendants when a parent selection changes and preserves draft on a revision conflict', async () => {
  current = filledSession()
  await render('/select', true)
  await until(() => expect(host.querySelector('#room')).not.toBeNull())
  await choose('room', 'test-room2')
  expect(host.querySelector<HTMLSelectElement>('#facility')?.value).toBe('')
  expect(host.querySelector<HTMLSelectElement>('#symptom')?.value).toBe('')
  saveConflict = true
  await click(button('저장하고 설문으로'))
  await until(() => expect(host.textContent).toContain('CONTEXT_CONFLICT'))
  expect(host.querySelector<HTMLSelectElement>('#room')?.value).toBe('test-room2')
  expect(count('/context', 'PUT')).toBe(1)
  await click(button('최신 입력 불러오기'))
  await until(() => expect(host.querySelector<HTMLSelectElement>('#room')?.value).toBe('test-room'))
})
it('evaluates interruptValues only after the answer save succeeds', async () => {
  current = filledSession()
  await render('/survey', true)
  await until(() => expect(host.textContent).toContain('시험용 위험 선택'))
  await radio('RISK')
  await until(() => expect(host.textContent).toContain('안전 확인 우선'))
  expect(current.context.answers?.['test-question']).toBe('RISK')
  expect(sent[0].expectedRevision).toBe(2)
  const paths = fetcher.mock.calls.map(([url]) => String(url))
  expect(paths.findIndex(path => path.endsWith('/context'))).toBeLessThan(paths.findIndex(path => path.endsWith('/evaluations')))
})
it('does not evaluate an interrupt answer whose save failed and marks the radio group error', async () => {
  current = filledSession(); saveConflict = true
  await render('/survey', true)
  await until(() => expect(host.textContent).toContain('시험용 위험 선택'))
  await radio('RISK')
  await until(() => expect(host.textContent).toContain('답을 저장하지 못했어요'))
  expect(sent).toHaveLength(0)
  expect(button('안내 결과 확인').disabled).toBe(true)
  expect(host.querySelector('input[value="RISK"]')?.getAttribute('aria-describedby')).toBe('answer-error')
})
it('restores keyboard focus to the selected radio after saving reveals a follow-up question', async () => {
  current = filledSession()
  await render('/survey', true)
  await until(() => expect(host.querySelector('input[value="TEST"]')).not.toBeNull())
  const before = host.querySelector<HTMLInputElement>('input[value="TEST"]')!
  await act(async () => before.focus())
  await click(before)
  await until(() => {
    const after = host.querySelector<HTMLInputElement>('input[value="TEST"]')!
    expect(after).not.toBe(before)
    expect(after.checked).toBe(true)
    expect(document.activeElement).toBe(after)
    expect(host.textContent).toContain('시험용 분기 질문')
  })
})
it('does not steal focus when the user moves elsewhere during answer saving', async () => {
  current = filledSession()
  const original = fetcher.getMockImplementation()!
  let completeSave: (() => void) | undefined
  fetcher.mockImplementation(async (url: string, opts: RequestInit = {}) => {
    if (url.endsWith('/context')) await new Promise<void>(resolve => { completeSave = resolve })
    return original(url, opts)
  })
  await render('/survey', true)
  await until(() => expect(host.querySelector('input[value="TEST"]')).not.toBeNull())
  const input = host.querySelector<HTMLInputElement>('input[value="TEST"]')!
  await act(async () => input.focus()); await click(input)
  await until(() => expect(completeSave).toBeDefined())
  const link = host.querySelector<HTMLAnchorElement>('a')!
  await act(async () => link.focus())
  await act(async () => completeSave!())
  await until(() => expect(host.querySelector<HTMLInputElement>('input[value="TEST"]')?.checked).toBe(true))
  expect(document.activeElement).toBe(link)
})
it('recovers a lost completed response by reading request state without another evaluation', async () => {
  current = filledSession(); evaluationMode = 'LOST'
  await render('/survey', true)
  await until(() => expect(button('안내 결과 확인').disabled).toBe(false))
  await click(button('안내 결과 확인'))
  await until(() => expect(host.textContent).toContain('평가 요청이 남아 있어요'))
  const request = readPending(sessionId)!
  expect(request).toEqual(sent[0])
  await click(button('완료 여부 확인'))
  await until(() => expect(host.textContent).toContain('현재 익명 상담에 저장됐어요'))
  expect(sent).toHaveLength(1)
  expect(readPending(sessionId)).toBeNull()
})
it('resends the same request id and revision after a network error', async () => {
  current = filledSession(); evaluationMode = 'LOST'
  await render('/survey', true)
  await until(() => expect(button('안내 결과 확인').disabled).toBe(false))
  await click(button('안내 결과 확인'))
  await until(() => expect(button('같은 요청 다시 보내기').disabled).toBe(false))
  evaluationMode = 'OK'
  await click(button('같은 요청 다시 보내기'))
  await until(() => expect(host.textContent).toContain('현재 익명 상담에 저장됐어요'))
  expect(sent).toHaveLength(2)
  expect(sent[1]).toEqual(sent[0])
})
it.each(['FAILED', 'DELETED'] as const)('does not recreate a %s request until the user explicitly starts another evaluation', async state => {
  current = filledSession(); recoveryState = state
  const old = { requestId: crypto.randomUUID(), expectedRevision: current.revision }
  storePending(sessionId, old)
  client.setQueryData(['result', sessionId, resultId, null, 'SURVEY'], result)
  await render('/survey', true)
  await until(() => expect(button('완료 여부 확인').disabled).toBe(false))
  await click(button('완료 여부 확인'))
  await until(() => expect(host.textContent).toContain(state === 'DELETED' ? '이 기록은 삭제됐어요' : '평가가 완료되지 않았어요'))
  expect(sent).toHaveLength(0)
  expect(readPending(sessionId)).toBeNull()
  if (state === 'DELETED') expect(client.getQueriesData({ queryKey: ['result', sessionId, resultId] })).toHaveLength(0)
  await click(button('새 평가로 다시 시도'))
  await until(() => expect(sent).toHaveLength(1))
  expect(sent[0].requestId).not.toBe(old.requestId)
})
it('observes PROCESSING wait time without automatic polling or creating a new id', async () => {
  current = filledSession(); recoveryState = 'PROCESSING'
  storePending(sessionId, { requestId: crypto.randomUUID(), expectedRevision: 1 })
  await render('/survey', true)
  await until(() => expect(button('완료 여부 확인').disabled).toBe(false))
  await click(button('완료 여부 확인'))
  await until(() => expect(host.textContent).toContain('평가를 처리하고 있어요'))
  expect(sent).toHaveLength(0)
  expect(count('/requests/')).toBe(1)
})
it('clears deleted requests on a 410 replay response and never automatically submits a new request', async () => {
  current = filledSession()
  storePending(sessionId, { requestId: crypto.randomUUID(), expectedRevision: 1 })
  const original = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (url: string, opts: RequestInit = {}) => String(url).endsWith('/evaluations') ? failure('REQUEST_DELETED', 410) : original(url, opts))
  await render('/survey', true)
  await until(() => expect(button('같은 요청 다시 보내기').disabled).toBe(false))
  await click(button('같은 요청 다시 보내기'))
  await until(() => expect(host.textContent).toContain('이 기록은 삭제됐어요'))
  expect(count('/evaluations', 'POST')).toBe(1)
  expect(readPending(sessionId)).toBeNull()
})
it('discards a late evaluation after logout and removes all private caches and consultation credentials', async () => {
  isMember = true; current = filledSession(true); evaluationMode = 'WAIT'
  await render('/survey', true)
  await until(() => expect(button('안내 결과 확인').disabled).toBe(false))
  await click(button('안내 결과 확인'))
  await until(() => expect(sent).toHaveLength(1))
  await click(button('로그아웃'))
  await until(() => expect(sessionStorage.length).toBe(0))
  await act(async () => release(json(result)))
  await until(() => expect(host.textContent).not.toContain('계정의 이전 결과에 저장됐어요'))
  expect(client.getQueriesData({ queryKey: ['result', sessionId, resultId] })).toHaveLength(0)
  expect(client.getQueryData(AUTH_KEY)).toEqual(anonymous)
})
it('starts a new member consultation without transferring a guest consultation when identity changes', async () => {
  current = filledSession(); storeSession(current, testToken)
  await render()
  isMember = true
  await act(async () => replaceAuth(client, member))
  await until(() => expect(button('새 설문 시작').disabled).toBe(false))
  await click(button('새 설문 시작'))
  await until(() => expect(host.querySelector('#room')).not.toBeNull())
  expect(sessionStorage.getItem('guest-session')).toBeNull()
  expect(sessionStorage.getItem('member-session-id')).toBe(sessionId)
  const call = fetcher.mock.calls.find(([url, options]) => String(url).endsWith('/sessions') && (options as RequestInit)?.method === 'POST')!
  expect((call[1] as RequestInit).headers).toMatchObject({ 'X-CSRF-Token': member.csrfToken })
  expect((call[1] as RequestInit).body).not.toContain(testToken)
  expect(current.context.answers).toEqual({})
})
it('opens member history after signing in at its guest gate without reloading', async () => {
  await render('/history')
  await until(() => expect(host.textContent).toContain('로그인 후 이용해 주세요'))
  isMember = true
  await act(async () => replaceAuth(client, member))
  await until(() => expect(host.querySelectorAll('.history-list li')).toHaveLength(1))
  expect(host.textContent).not.toContain('정보를 확인하고 있어요')
})
it('loads member history pages and deletes only question records with CSRF', async () => {
  isMember = true; current = filledSession(true); result = resultFixture(current)
  await render('/history')
  await until(() => expect(host.querySelectorAll('.history-list li')).toHaveLength(1))
  await click(button('더 보기'))
  await until(() => expect(host.querySelectorAll('.history-list li')).toHaveLength(2))
  await click(button('내 질문 기록 전체 삭제')); await click(button('삭제 확인'))
  await until(() => expect(host.textContent).toContain('저장된 안내 결과는 남아 있어요'))
  expect(host.querySelectorAll('.history-list li')).toHaveLength(2)
  const call = fetcher.mock.calls.find(([url]) => String(url).endsWith('/me/question-records'))!
  expect((call[1] as RequestInit).headers).toMatchObject({ 'X-CSRF-Token': member.csrfToken })
  expect(count('/me/results/' + resultId, 'DELETE')).toBe(0)
})
it.each(['/history', '/history/' + resultId])('keeps keyboard focus through deletion confirmation and cancellation at %s', async path => {
  isMember = true; current = filledSession(true); result = resultFixture(current)
  await render(path)
  const label = path === '/history' ? '내 질문 기록 전체 삭제' : '이 결과 삭제'
  await until(() => expect(host.textContent).toContain(label))
  await click(button(label))
  expect(document.activeElement).toBe(button('취소'))
  expect(button('취소').getAttribute('aria-describedby')).toBeTruthy()
  await click(button('취소'))
  expect(document.activeElement).toBe(button(label))
  expect(count('/me/', 'DELETE')).toBe(0)
})
it('deletes a member result and evicts its detail and current-result caches', async () => {
  isMember = true; current = filledSession(true); result = { ...resultFixture(current), isCurrent: false }
  client.setQueryData(['result', sessionId, resultId, member.user!.id, 'SURVEY'], result)
  await render('/history/' + resultId)
  await until(() => expect(host.textContent).toContain('과거 결과예요'))
  await click(button('이 결과 삭제')); await click(button('삭제 확인'))
  await until(() => expect(count('/me/results/' + resultId, 'DELETE')).toBe(1))
  await until(() => expect(client.getQueriesData({ queryKey: ['history-result', resultId] })).toHaveLength(0))
  expect(client.getQueriesData({ queryKey: ['result', sessionId, resultId] })).toHaveLength(0)
})
it('ends an anonymous consultation with an explicit question erasure option', async () => {
  current = filledSession()
  await render('/select', true)
  await until(() => expect(host.querySelector('#room')).not.toBeNull())
  await click(button('상담 종료'))
  await click(host.querySelector<HTMLInputElement>('input[type=checkbox]')!)
  await click(button('종료 확인'))
  await until(() => expect(sessionStorage.getItem('guest-session')).toBeNull())
  expect(count('?eraseRecords=true', 'DELETE')).toBe(1)
})
it('clears membership and protected content when a history read reports expired authentication', async () => {
  isMember = true; current = filledSession(true); storeSession(current, null)
  const original = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (url: string, opts: RequestInit = {}) => String(url).endsWith('/me/results') ? failure('AUTH_EXPIRED', 401) : original(url, opts))
  await render('/history')
  await until(() => expect(host.textContent).toContain('로그인 후 이용해 주세요'))
  expect(sessionStorage.getItem('member-session-id')).toBeNull()
  expect(host.querySelector('.history-list')).toBeNull()
})
it('erases an old member consultation and private result cache when account revalidation detects another identity', async () => {
  isMember = true; current = filledSession(true); result = resultFixture(current)
  await render('/history', true)
  await until(() => expect(host.querySelectorAll('.history-list li')).toHaveLength(1))
  client.setQueryData(['history-result', resultId, member.user!.id, 'SURVEY'], result)
  const original = fetcher.getMockImplementation()!
  const other = { ...member, user: { ...member.user!, id: crypto.randomUUID() } }
  fetcher.mockImplementation(async (url: string, opts: RequestInit = {}) => String(url).endsWith('/auth/me') ? json(other) : original(url, opts))
  await act(async () => { await client.invalidateQueries({ queryKey: AUTH_KEY }) })
  await until(() => expect(sessionStorage.getItem('member-session-id')).toBeNull())
  expect(client.getQueryData(['history-result', resultId, member.user!.id, 'SURVEY'])).toBeUndefined()
})
it.each(['/result/', '/history/'])('does not display another identity or unscoped result cache at %s', async path => {
  isMember = true; current = filledSession(true); result = resultFixture(current)
  const prefix = path === '/result/' ? ['result', sessionId, resultId] : ['history-result', resultId]
  const privateResult = { ...result, guidance: ['이전 계정의 비공개 안내'] }
  client.setQueryDefaults([prefix[0]], { staleTime: Infinity })
  client.setQueryData(prefix, privateResult)
  client.setQueryData([...prefix, 'another-member', 'SURVEY'], privateResult)
  await render(path + resultId, path === '/result/')
  await until(() => expect(host.textContent).toContain(result.guidance[0]))
  expect(host.textContent).not.toContain('이전 계정의 비공개 안내')
  expect(count('/me/results/' + resultId)).toBe(1)
  expect(client.getQueryData([...prefix, member.user!.id, 'SURVEY'])).toEqual(result)
})
it('treats history storage failure as an error instead of an empty history', async () => {
  isMember = true
  const original = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (url: string, opts: RequestInit = {}) => String(url).endsWith('/me/results') ? failure('SERVICE_UNAVAILABLE', 503) : original(url, opts))
  await render('/history')
  await until(() => expect(host.textContent).toContain('SERVICE_UNAVAILABLE'))
  expect(host.textContent).not.toContain('저장된 이전 결과가 없어요')
})
it('shows empty history only after a successful empty list response', async () => {
  isMember = true
  const original = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (url: string, opts: RequestInit = {}) => String(url).endsWith('/me/results') ? json({ items: [], nextCursor: null }) : original(url, opts))
  await render('/history')
  await until(() => expect(host.textContent).toContain('저장된 이전 결과가 없어요'))
  expect(host.querySelector('.error-panel')).toBeNull()
})
it('clears guest recovery data if evaluation reports a server-expired consultation', async () => {
  current = filledSession()
  const original = fetcher.getMockImplementation()!
  fetcher.mockImplementation(async (url: string, opts: RequestInit = {}) => String(url).endsWith('/evaluations') ? failure('SESSION_EXPIRED', 401) : original(url, opts))
  await render('/survey', true)
  await until(() => expect(button('안내 결과 확인').disabled).toBe(false))
  await click(button('안내 결과 확인'))
  await until(() => expect(host.textContent).toContain('상담이 없거나 만료·종료됐어요'))
  expect(sessionStorage.getItem('guest-session')).toBeNull()
  expect(readPending(sessionId)).toBeNull()
})
it('renders user content as text and only links reviewed https sources', async () => {
  isMember = true; current = filledSession(true)
  result = resultFixture(current)
  result.summary.description = '<img src=x onerror="alert(1)">'
  result.citations = [{ chunkId: crypto.randomUUID(), documentVersionId: crypto.randomUUID(), title: '시험용 법령', locator: '시험 조항', url: 'javascript:alert(1)', effectiveDate: null, kind: 'LAW_CRITERIA', use: 'RELATED', reviewedAt: new Date().toISOString(), reviewUntil: new Date(Date.now() + 86400000).toISOString() }]
  await render('/history/' + resultId)
  await until(() => expect(host.textContent).toContain(result.summary.description))
  expect(host.querySelector('img')).toBeNull()
  expect(host.querySelector('a[href^="javascript:"]')).toBeNull()
  expect(host.textContent).toContain('법령 기준 · 참고 자료')
})
