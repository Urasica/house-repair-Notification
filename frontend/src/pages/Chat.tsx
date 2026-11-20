import { useCallback, useEffect, useRef, useState } from 'react'
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'
import { Feedback, Waiting } from '../components/Feedback'
import SurveyImport from '../components/SurveyImport'
import RepairExamples from '../components/RepairExamples'
import { EvidenceSources, LawExplanations } from '../components/EvidenceSources'
import { useAuth } from '../features/auth/useAuth'
import { chatHistory, importSurvey, pendingChat, saveChatPending, sendChat } from '../features/chat/api'
import type { ChatResponse } from '../features/chat/api'
import { createSession, endSession, getCatalog, getSession, requestState } from '../features/survey/api'
import { clearSession, identityEpoch, storedReference, storeSession } from '../features/survey/storage'
import { useSurvey } from '../features/survey/useSurvey'
import type { Pending, Session, SessionRef } from '../features/survey/storage'
import { referenceIsActive } from '../features/survey/useEvaluation'
import { useRetryDelay } from '../features/survey/useRetryDelay'
import { statusLabels } from '../features/survey/status'
import { localTime } from '../features/survey/time'

const sentenceSegmenter = typeof Intl.Segmenter === 'function'
  ? new Intl.Segmenter('ko', { granularity: 'sentence' })
  : null

function answerParagraphs(content: string) {
  return content.trim().split(/\r?\n(?:[ \t]*\r?\n)+/).flatMap(paragraph => {
    if (!sentenceSegmenter || paragraph.length <= 120 || paragraph.includes('\n')) return [paragraph]
    return Array.from(sentenceSegmenter.segment(paragraph), part => part.segment.trim())
  }).filter(Boolean)
}

export default function Chat() {
  const { auth, reference, query, client } = useSurvey('CHAT')
  const attempted = useRef(false)
  const guard = useRef(false)
  const { mutateAsync, isPending: creating, error } = useMutation({ mutationFn: async () => {
    if (guard.current || !auth.data?.user || auth.isError) return
    const epoch = identityEpoch(), before = storedReference(true, 'CHAT')
    guard.current = true
    try {
      const catalog = await getCatalog()
      const created = await createSession(catalog.version, auth.data.csrfToken, 'CHAT')
      if (identityEpoch() !== epoch || storedReference(true, 'CHAT') !== before) return
      client.setQueryData(['chat-session', created.session.id, auth.data.user.id, 'CHAT'], created.session)
      storeSession(created.session, null)
    } finally { guard.current = false }
  }, retry: false })
  const start = useCallback(async () => { await mutateAsync().catch(() => undefined) }, [mutateAsync])
  useEffect(() => {
    if (attempted.current || auth.isPending || auth.isError || !auth.data?.user) return
    attempted.current = true
    if (!reference) void start()
  }, [auth.isPending, auth.isError, auth.data, reference, start])
  if (auth.isPending || creating || (reference && query.isPending)) return <Waiting />
  if (reference && query.data && query.data.purpose === 'CHAT') return <Conversation key={query.data.id} session={query.data} reference={reference} restart={start} />
  return <section className="notice chat-panel"><h1>새 대화를 시작해 주세요</h1>
    <p>설문 작성 없이 궁금한 내용을 바로 질문할 수 있어요.</p>
    {(error || query.error) && <Feedback error={error || query.error} />}
    <button disabled={creating} onClick={() => void start()}>{error ? '새 대화 다시 시작' : '새 대화 시작'}</button>
  </section>
}

function Conversation({ session, reference, restart }: { session: Session; reference: SessionRef; restart: () => Promise<void> }) {
  const auth = useAuth()
  const client = useQueryClient()
  const catalog = useQuery({ queryKey: ['catalog', session.catalogVersion], queryFn: ({ signal }) => getCatalog(session.catalogVersion, signal), retry: false })
  const history = useInfiniteQuery({ queryKey: ['chat', session.id, auth.data?.user?.id, 'CHAT'], initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => chatHistory(reference, pageParam, signal),
    getNextPageParam: page => page.nextCursor, retry: false, refetchOnWindowFocus: false })
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<Pending | null>(() => pendingChat(session.id))
  const [pendingContent, setPendingContent] = useState<string | null>(null)
  const guard = useRef(false)
  const input = useRef<HTMLTextAreaElement>(null)
  const thread = useRef<HTMLDivElement>(null)
  const [showSidebar, setShowSidebar] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [latest, setLatest] = useState<ChatResponse[]>([])
  const delay = useRetryDelay()
  async function loadSurvey(resultId: string) {
    if (guard.current || pending || resetting || confirmReset || delay.waiting) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null); setNotice('설문을 불러오고 있어요.')
    try {
      const saved = await importSurvey(reference, { resultId, expectedRevision: session.revision }, auth.data?.csrfToken)
      if (!referenceIsActive(reference, epoch)) return
      client.setQueryData(['chat-session', session.id, auth.data?.user?.id, 'CHAT'], saved)
      void client.invalidateQueries({ queryKey: ['chat', session.id] })
      setNotice('선택한 설문을 불러왔어요. 확인한 내용을 참고해 다음 질문에 답할게요.')
      input.current?.focus()
    } catch (cause) {
      if (referenceIsActive(reference, epoch)) { setError(cause); setNotice(''); if (cause instanceof ApiError && cause.code === 'CONTEXT_CONFLICT') void client.invalidateQueries({ queryKey: ['chat-session', session.id] }) }
      throw cause
    } finally { guard.current = false; if (referenceIsActive(reference, epoch)) setBusy(false) }
  }
  const items = [...new Map([...latest, ...(history.data?.pages.flatMap(page => page.items) ?? [])].map(item => [item.requestId, item])).values()]
    .sort((a, b) => a.userMessage.createdAt.localeCompare(b.userMessage.createdAt))
  const lastRequest = items.at(-1)?.requestId
  const sending = pendingContent !== null && !items.some(item => item.requestId === pending?.requestId)
  useEffect(() => {
    const panel = thread.current
    const turn = panel?.querySelector<HTMLElement>('.chat-list > li:last-child')
    if (panel && turn) panel.scrollTop = turn.offsetTop
  }, [lastRequest, sending])
  function clear() { saveChatPending(session.id, null); setPending(null); setPendingContent(null) }
  function complete(result: ChatResponse) {
    clear(); setDraft(''); setNotice('대화가 저장됐어요.')
    setLatest(values => [...values.filter(item => item.requestId !== result.requestId), result])
    void client.invalidateQueries({ queryKey: ['chat', session.id] })
    client.setQueriesData<Session>({ queryKey: ['chat-session', session.id] }, saved => saved ? { ...saved, revision: result.contextRevision } : saved)
    void client.invalidateQueries({ queryKey: ['chat-session', session.id] })
    input.current?.focus()
  }
  function fail(cause: unknown) {
    setError(cause); delay.pause(cause)
    if (cause instanceof ApiError && ['REQUEST_DELETED', 'REQUEST_FAILED', 'IDEMPOTENCY_CONFLICT', 'CONTEXT_CONFLICT', 'RATE_LIMITED'].includes(cause.code)) {
      clear(); setNotice('전송을 완료하지 못했어요. 내용을 확인하고 직접 새로 보내 주세요.')
      if (cause.code === 'CONTEXT_CONFLICT') void client.invalidateQueries({ queryKey: ['chat-session', session.id] })
      if (cause.code === 'REQUEST_DELETED') { setLatest([]); void client.invalidateQueries({ queryKey: ['chat', session.id] }) }
    }
  }
  async function execute(request: Pending, content: string) {
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null); setNotice('')
    try {
      const result = await sendChat(reference, request, content, auth.data?.csrfToken)
      if (referenceIsActive(reference, epoch)) complete(result)
    } catch (cause) { if (referenceIsActive(reference, epoch)) fail(cause) }
    finally { guard.current = false; if (referenceIsActive(reference, epoch)) setBusy(false) }
  }
  function submit() {
    if (guard.current || resetting || confirmReset || pendingChat(session.id) || delay.waiting || !draft.trim()) return
    const request = { requestId: crypto.randomUUID(), expectedRevision: session.revision }
    saveChatPending(session.id, request); setPending(request); setPendingContent(draft)
    void execute(request, draft)
  }
  async function recover() {
    if (!pending || guard.current || delay.waiting) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null)
    try {
      const state = await requestState(reference, pending)
      if (!referenceIsActive(reference, epoch)) return
      if (state.kind === 'CHAT' && state.state === 'COMPLETED' && state.response && 'assistantMessage' in state.response) complete(state.response)
      else if (state.state === 'FAILED' || state.state === 'DELETED') { clear(); setNotice('완료되지 않았거나 삭제된 요청이에요. 필요하면 직접 새로 보내 주세요.') }
      else { setNotice('처리 중이에요. 잠시 후 완료 여부를 확인해 주세요.'); delay.pause(new ApiError('REQUEST_IN_PROGRESS', '처리 중', 409, null, { retryAfterMs: state.retryAfterMs ?? 1000 })) }
    } catch (cause) {
      if (!referenceIsActive(reference, epoch)) return
      if (cause instanceof ApiError && cause.code === 'NOT_FOUND') {
        try { await getSession(reference) } catch (check) { if (referenceIsActive(reference, epoch)) fail(check); return }
        if (!referenceIsActive(reference, epoch)) return
        if (pendingContent === null) { clear(); setNotice('저장된 요청이 없어요. 질문을 다시 입력해 주세요.') }
        else setNotice('저장된 요청이 없어요. 같은 요청으로 다시 보낼 수 있어요.')
      } else fail(cause)
    } finally { guard.current = false; if (referenceIsActive(reference, epoch)) setBusy(false) }
  }
  useEffect(() => { if (!confirmReset) input.current?.focus() }, [confirmReset])
  async function reset() {
    if (guard.current || pending || resetting) return
    const epoch = identityEpoch()
    guard.current = true; setResetting(true); setError(null)
    try {
      try { await endSession(reference, auth.data?.csrfToken) }
      catch (cause) {
        if (cause instanceof ApiError && cause.status === 404) { /* Already closed. */ }
        else if (!(cause instanceof ApiError) || cause.status >= 500) {
          let closed = false
          try { await getSession(reference) }
          catch (check) { if (check instanceof ApiError && check.status === 404) closed = true; else throw check }
          if (!closed) throw cause
        } else throw cause
      }
      if (identityEpoch() !== epoch) return
      clearSession(reference)
      const oldChat = { predicate: (q: { queryKey: readonly unknown[] }) => ['chat', 'chat-session'].includes(String(q.queryKey[0])) && q.queryKey[1] === session.id }
      await client.cancelQueries(oldChat)
      client.removeQueries(oldChat)
      await restart()
    } catch (cause) { if (identityEpoch() === epoch) { setError(cause); setConfirmReset(false) } }
    finally { guard.current = false; if (identityEpoch() === epoch) setResetting(false) }
  }
  const contextLabels = [
    catalog.data?.housingTypes.find(item => item.id === session.context.housingType)?.label,
    catalog.data?.rooms.find(item => item.id === session.context.roomId)?.label,
    catalog.data?.facilities.find(item => item.id === session.context.facilityId)?.label,
    catalog.data?.symptoms.find(item => item.id === session.context.symptomId)?.label,
  ].filter(Boolean)
  const answerCount = Object.keys(session.context.answers ?? {}).length
  const inputLocked = busy || !!pending || confirmReset || resetting
  return <section className="chat-workspace" aria-label="보수 상담 챗봇">
    <header className="chat-heading">
      <h1>보수 상담 챗봇</h1>
      <button type="button" className="secondary chat-sidebar-toggle" aria-controls="chat-sidebar" aria-expanded={showSidebar} onClick={() => setShowSidebar(!showSidebar)}>대화 정보</button>
    </header>
    <aside id="chat-sidebar" className="chat-sidebar" data-open={showSidebar} aria-label="대화 정보">
      <button type="button" className="secondary" disabled={busy || !!pending || resetting} onClick={() => setConfirmReset(true)}>대화 초기화</button>
    {confirmReset && <section className="notice confirm-panel" role="group" aria-label="대화 초기화 확인">
      <p>현재 대화와 챗봇에서 확인한 내용이 지워지고 새 대화를 시작합니다.<br />설문·결과 이력과 별도 보존되는 질문 분석 기록은 유지됩니다.</p>
      <div className="actions"><button className="danger" disabled={resetting} onClick={() => void reset()}>초기화 확인</button>
      <button className="secondary" disabled={resetting} onClick={() => { setConfirmReset(false); input.current?.focus() }}>취소</button></div>
    </section>}
      <div className="chat-context"><h2>확인한 내용</h2>
        {contextLabels.length || answerCount ? <ul>{contextLabels.map(label => <li key={label}>{label}</li>)}{!!answerCount && <li>설문 답변 {answerCount}개</li>}</ul> : <p>아직 확인한 내용이 없어요.</p>}
      </div>
      <div className="chat-privacy">
        <h2>대화와 개인정보</h2>
        <p>이 창에서 대화를 이어갈 수 있어요.</p>
        <p>질문 원문은 상담 만료 후 7일 이내 정리해요.<br />식별정보가 없는 분류·선택 정보는 기본 5년 보관해요.</p>
        <p>OpenAI에는 선택·답변 라벨, 조문 번호와 검토 자료만 보내요.</p>
      </div>
    </aside>
    <div className="chat-main">
      <div ref={thread} className="chat-thread" role="region" aria-label="상담 대화" tabIndex={0}>
        {history.isPending && <Waiting />}
        {history.isError && <Feedback error={history.error} retry={() => void history.refetch()} />}
        {history.data && !items.length && !sending && <div className="chat-welcome"><h2>어디가 불편하신가요?</h2><p>증상이나 궁금한 조문을 적어 주세요.<br />필요한 내용은 대화에서 하나씩 확인할게요.</p></div>}
        <ol className="chat-list" aria-label="저장된 대화">{items.map(item => <li key={item.requestId}>
      <p className="chat-bubble chat-content"><span className="sr-only">내 질문. </span>{item.userMessage.content}</p>
      <article className="chat-answer" aria-label="챗봇 답변">
        <h2>{statusLabels[item.status]}</h2><p className="chat-meta">{item.answerMode === 'GROUNDED' ? '근거 확인 답변 · ' : item.answerMode === 'CLARIFY' ? '추가 확인 · ' : ''}<time dateTime={item.assistantMessage.createdAt}>{localTime(item.assistantMessage.createdAt)}</time></p>
        {(!item.isCurrent || item.contextRevision !== session.revision) && <p className="past-note">이전 입력이나 기준의 답변이에요.<br />현재 상황과 다를 수 있어요.</p>}
        <div aria-label="답변 내용">
          <LawExplanations citations={item.assistantMessage.citations} />
          {answerParagraphs(item.assistantMessage.content).map((text, index) => <p key={index} className="chat-content">{text}</p>)}
        </div>
        {!!item.followUpQuestions.length && <ul>{item.followUpQuestions.map((question, index) => <li key={index}>{question}</li>)}</ul>}
        <RepairExamples examples={item.referenceExamples} />
        <EvidenceSources citations={item.assistantMessage.citations} />
        <p>{item.disclaimer}</p></article>
    </li>)}{sending && <li><p className="chat-bubble chat-content"><span className="sr-only">내 질문. </span>{pendingContent}</p></li>}</ol>
        {history.hasNextPage && <button className="secondary" disabled={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>다음 대화 보기</button>}
      </div>
      <div className="chat-compose-area">
        {error != null && <Feedback error={error} />}
        <p className="chat-status" role="status">{busy ? notice || '답변을 확인하고 있어요.' : notice}</p>
        {pending && !busy && <div className="chat-recovery"><p>이전 질문의 전송 결과를 확인해 주세요.</p>
          <button type="button" disabled={busy || delay.waiting} onClick={() => void recover()}>전송 결과 확인</button>
          {pendingContent !== null && <button type="button" className="secondary" disabled={busy || delay.waiting} onClick={() => { if (!guard.current && pendingContent !== null) void execute(pending, pendingContent) }}>같은 요청 다시 보내기</button>}
        </div>}
        <form className="chat-composer" onSubmit={event => { event.preventDefault(); submit() }}>
          <label className="sr-only" htmlFor="chat-input">궁금한 내용</label>
          <textarea id="chat-input" ref={input} value={sending ? '' : draft} onChange={event => setDraft(event.target.value)} onKeyDown={event => {
            if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) { event.preventDefault(); submit() }
          }} maxLength={2000} required disabled={inputLocked} rows={1} placeholder="예: 주방 싱크대 아래에서 물이 새요" aria-describedby="chat-help" />
          <div className="chat-composer-actions">
            <SurveyImport disabled={inputLocked || delay.waiting} load={loadSurvey} />
            <button type="submit" disabled={inputLocked || delay.waiting || !draft.trim()}>질문 보내기</button>
          </div>
        </form>
        <p id="chat-help">이름·주소·연락처는 적지 마세요. <span>Enter로 보내기 · Shift+Enter로 줄바꿈</span></p>
      </div>
    </div>
  </section>
}
