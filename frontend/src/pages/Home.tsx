import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { createSession, getCatalog } from '../features/survey/api'
import { useSurvey } from '../features/survey/useSurvey'
import { clearSession, identityEpoch, storeSession } from '../features/survey/storage'
import { Feedback, Waiting } from '../components/Feedback'

export default function Home() {
  const { auth, reference, query, client } = useSurvey()
  const catalog = useQuery({ queryKey: ['catalog-ready'], queryFn: () => getCatalog(), retry: false })
  const navigate = useNavigate()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const guard = useRef(false)
  const preparing = catalog.error instanceof ApiError && catalog.error.code === 'CATALOG_NOT_READY'
  async function start() {
    if (!catalog.data || guard.current || auth.isError || auth.isPending) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null)
    try {
      const created = await createSession(catalog.data.version, auth.data?.csrfToken)
      if (identityEpoch() !== epoch) return
      await client.cancelQueries({ predicate: q => q.queryKey[0] !== 'auth' && q.queryKey[0] !== 'catalog-ready' })
      if (identityEpoch() !== epoch) return
      client.removeQueries({ predicate: q => q.queryKey[0] !== 'auth' && q.queryKey[0] !== 'catalog-ready' })
      if (reference) clearSession(reference)
      storeSession(created.session, created.sessionToken)
      client.setQueryData(['session', created.session.id], created.session)
      void navigate('/select')
    } catch (cause) {
      if (identityEpoch() !== epoch) return
      setError(cause)
      if (cause instanceof ApiError && cause.code === 'CATALOG_UPDATED') void catalog.refetch()
    } finally { guard.current = false; if (identityEpoch() === epoch) setBusy(false) }
  }
  return <>
    <section className="intro" aria-labelledby="page-title">
      <p className="eyebrow">우리 집의 불편함, 차근차근 확인해요</p>
      <h1 id="page-title">보수 안내를<br />쉽고 편안하게.</h1>
      <p className="description">주택과 증상을 선택하고 간단한 질문에 답하면,<br className="desktop-break" /> 관련 기준과 문의할 내용을 안내해 드려요.</p>
      <ol className="steps"><li>주택·증상 선택</li><li>간단 설문</li><li>안내 결과 확인</li></ol>
    </section>
    <section className="notice" aria-live="polite" aria-labelledby="notice-title">
      {catalog.isPending ? <Waiting /> : preparing ? <><h2 id="notice-title">안내 서비스를 준비하고 있어요</h2><p>정확한 안내를 위해 증상 목록과 관련 자료를 준비하고 있어요. 준비가 끝나면 설문을 시작할 수 있어요.</p><button disabled>설문 준비 중</button></> : catalog.isError ? <Feedback error={catalog.error} retry={() => void catalog.refetch()} /> : <>
        <h2 id="notice-title">간단 설문으로 확인해 보세요</h2><p>{auth.data?.user ? '새 상담 결과는 계정의 이전 결과에서 확인할 수 있어요.' : '로그인 없이 설문을 할 수 있어요. 결과는 현재 익명 상담에 저장돼요.'}</p>
        <button disabled={busy || auth.isPending || auth.isError} onClick={() => void start()}>{busy ? '상담을 시작하고 있어요' : '새 설문 시작'}</button>
      </>}
      {reference && query.data && !query.isError && <p className="continue-link"><Link to={query.data.currentResultId ? '/result/' + query.data.currentResultId : '/survey'}>진행 중인 상담 이어가기</Link></p>}
      {auth.isError && <Feedback error={auth.error} retry={() => void auth.refetch()} />}
      {!!error && <Feedback error={error} />}
    </section>
    <section className="notice" aria-labelledby="privacy-title">
      <h2 id="privacy-title">입력과 기록은 이렇게 사용해요</h2>
      <p>상담과 로그인은 24시간 동안 유효해요. 원본 상담·대화·비회원 결과는 상담 만료 후 7일 이내 삭제해요. 회원 안내 결과는 입력·답변·출처와 함께 기본 5년 보관하며 이전 결과에서 삭제할 수 있어요.</p>
      <p>식별정보를 제외한 질문 분류·선택 정보는 서비스 개선을 위해 기본 5년 보관해요. 회원은 이전 결과에서, 비회원은 상담 종료 전에 질문 기록 삭제를 선택할 수 있어요. 이름·주소·연락처는 입력하지 마세요.</p>
      <p>자료 검색과 답변을 위해 OpenAI에 선택 라벨·조문 번호와 검토 자료를 보낼 수 있어요. 질문 원문은 보내지 않아요. 답변 저장을 요청하지 않는 설정과 제공자의 데이터 보존 정책은 서로 다르며, 제공자 정책은 별도로 적용돼요.</p>
    </section>
  </>
}
