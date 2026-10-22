import { useCallback, useEffect, useRef, useState } from 'react'
import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { ApiError } from '../api/client'
import { Feedback, Waiting } from '../components/Feedback'
import { useAuth } from '../features/auth/useAuth'
import { chatHistory, pendingChat, saveChatPending, sendChat } from '../features/chat/api'
import type { ChatResponse } from '../features/chat/api'
import { createSession, endSession, getCatalog, getSession, requestState } from '../features/survey/api'
import { clearSession, identityEpoch, storedReference, storeSession } from '../features/survey/storage'
import { useSurvey } from '../features/survey/useSurvey'
import type { Pending, Session, SessionRef } from '../features/survey/storage'
import { referenceIsActive } from '../features/survey/useEvaluation'
import { useRetryDelay } from '../features/survey/useRetryDelay'
import { statusLabels } from '../features/survey/status'
import { localTime } from '../features/survey/time'

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
  const history = useInfiniteQuery({ queryKey: ['chat', session.id, auth.data?.user?.id, 'CHAT'], initialPageParam: null as string | null,
    queryFn: ({ pageParam, signal }) => chatHistory(reference, pageParam, signal),
    getNextPageParam: page => page.nextCursor, retry: false, refetchOnWindowFocus: false })
  const [draft, setDraft] = useState('')
  const [pending, setPending] = useState<Pending | null>(() => pendingChat(session.id))
  const [pendingContent, setPendingContent] = useState<string | null>(null)
  const guard = useRef(false)
  const input = useRef<HTMLTextAreaElement>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const [notice, setNotice] = useState('')
  const [confirmReset, setConfirmReset] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [latest, setLatest] = useState<ChatResponse[]>([])
  const delay = useRetryDelay()
  const items = [...new Map([...latest, ...(history.data?.pages.flatMap(page => page.items) ?? [])].map(item => [item.requestId, item])).values()]
    .sort((a, b) => a.userMessage.createdAt.localeCompare(b.userMessage.createdAt))
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
  return <section className="notice chat-panel">
    <p className="eyebrow">회원 상담</p><h1>검토된 자료로 질문하기</h1>
    <p>관련 조문 원문과 확인할 내용을 안내해요. 보수·비용·교체 여부는 담당 기관 확인이 필요해요.</p>
    <p>설문과 별도로 답변해요. 필요한 내용은 이 대화에서 확인할게요.</p>
    <button className="secondary" disabled={busy || !!pending || resetting} onClick={() => setConfirmReset(true)}>대화 초기화</button>
    {confirmReset && <section className="notice confirm-panel" role="group" aria-label="대화 초기화 확인">
      <p>현재 대화와 챗봇에서 확인한 내용이 지워지고 새 대화를 시작합니다. 설문·결과 이력과 별도 보존되는 질문 분석 기록은 유지됩니다.</p>
      <div className="actions"><button className="danger" disabled={resetting} onClick={() => void reset()}>초기화 확인</button>
      <button className="secondary" disabled={resetting} onClick={() => { setConfirmReset(false); input.current?.focus() }}>취소</button></div>
    </section>}
    <p className="muted">질문 원문과 대화는 상담 만료 후 7일 이내 정리해요. 식별정보를 제외한 질문 분류·선택 정보는 기본 5년 보관해요. OpenAI에는 선택 라벨·조문 번호와 검토 자료만 보내요. 이름·주소·연락처는 입력하지 마세요.</p>
    {history.isPending && <Waiting />}
    {history.isError && <Feedback error={history.error} retry={() => void history.refetch()} />}
    {history.data && !items.length && <p role="status">새 대화가 준비됐어요. 궁금한 조문이나 증상을 바로 질문해 주세요.</p>}
    <ol className="chat-list" aria-label="저장된 대화">{items.map(item => <li key={item.requestId}>
      <article><h2>내 질문</h2><p className="chat-content">{item.userMessage.content}</p>
        <h2>{statusLabels[item.status]}</h2><p className="eyebrow">{item.answerMode === 'GROUNDED' ? '근거 확인 답변' : item.answerMode === 'CLARIFY' ? '추가 확인' : '기본 안내'} · {localTime(item.assistantMessage.createdAt)}</p>
        {(!item.isCurrent || item.contextRevision !== session.revision) && <p className="past-note">이전 입력이나 기준의 답변이에요. 현재 상황과 다를 수 있어요.</p>}
        <p className="chat-content">{item.assistantMessage.content}</p>
        {!!item.followUpQuestions.length && <ul>{item.followUpQuestions.map((question, index) => <li key={index}>{question}</li>)}</ul>}
        {!!item.assistantMessage.citations.length && <ul aria-label="정보 출처">{item.assistantMessage.citations.map(citation => <li key={citation.chunkId}>
          <details><summary>{citation.use === 'RELATED' ? '참고 자료' : '설명 근거'} · {citation.title} · {citation.locator}</summary>
            {citation.excerpt && <p className="chat-content">{citation.excerpt}</p>}
            <p>시행일: {citation.effectiveDate ?? '미확인'} · 검토: {localTime(citation.reviewedAt)} · 검토 기한: {localTime(citation.reviewUntil)}</p>
            {/^https:\/\//.test(citation.url) && <a href={citation.url} target="_blank" rel="noopener noreferrer">원문 확인 (선택)</a>}
          </details>
        </li>)}</ul>}<p>{item.disclaimer}</p></article>
    </li>)}</ol>
    {history.hasNextPage && <button className="secondary" disabled={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>다음 대화 보기</button>}
    {error != null && <Feedback error={error} />}
    <p role="status">{busy ? '답변을 확인하고 저장하고 있어요.' : notice}</p>
    {pending && <div className="notice"><p>이전 전송의 완료 여부를 먼저 확인해 주세요. 새로고침 후에도 중복 전송하지 않아요.</p>
      <button disabled={busy || delay.waiting} onClick={() => void recover()}>전송 결과 확인</button>
      {pendingContent !== null && <button className="secondary" disabled={busy || delay.waiting} onClick={() => { if (!guard.current && pendingContent !== null) void execute(pending, pendingContent) }}>같은 요청 다시 보내기</button>}
    </div>}
    <form onSubmit={event => { event.preventDefault(); submit() }}>
      <label htmlFor="chat-input">궁금한 내용</label>
      <textarea id="chat-input" ref={input} value={draft} onChange={event => setDraft(event.target.value)} maxLength={2000} required disabled={busy || !!pending || confirmReset || resetting} rows={4} aria-describedby="chat-help" />
      <p id="chat-help">최대 2,000자 · 예: 제10조 내용을 알려 주세요.</p>
      <button type="submit" disabled={busy || !!pending || confirmReset || resetting || delay.waiting || !draft.trim()}>질문 보내기</button>
    </form>
  </section>
}
