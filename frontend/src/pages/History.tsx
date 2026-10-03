import { useRef, useState } from 'react'
import { useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { Feedback, Waiting } from '../components/Feedback'
import ResultView from '../components/ResultView'
import { useAuth } from '../features/auth/useAuth'
import { deleteQuestions, deleteResult, getHistory, getHistoryResult } from '../features/survey/api'
import { identityEpoch } from '../features/survey/storage'
import { localTime } from '../features/survey/time'
import { statusLabels } from '../features/survey/status'

function DeleteRecord({ resultId }: { resultId?: string }) {
  const auth = useAuth()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState('')
  const [error, setError] = useState<unknown>(null)
  const guard = useRef(false)
  async function erase() {
    if (!auth.data?.csrfToken || guard.current) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null)
    try {
      if (resultId) await deleteResult(resultId, auth.data.csrfToken)
      else await deleteQuestions(auth.data.csrfToken)
      if (epoch !== identityEpoch()) return
      await client.cancelQueries({ predicate: query => ['result', 'history-result', 'history'].includes(String(query.queryKey[0])) })
      if (epoch !== identityEpoch()) return
      if (resultId) {
        client.removeQueries({ predicate: query => (query.queryKey[0] === 'history-result' && query.queryKey[1] === resultId) || (query.queryKey[0] === 'result' && query.queryKey[2] === resultId) })
        void client.invalidateQueries({ queryKey: ['session'] })
        void client.invalidateQueries({ queryKey: ['history'] })
        void navigate('/history', { replace: true })
      } else {
        setMessage('질문 기록을 삭제했어요. 저장된 안내 결과는 남아 있어요.')
      }
      setConfirming(false)
    } catch (cause) { if (epoch === identityEpoch()) setError(cause) }
    finally { guard.current = false; if (epoch === identityEpoch()) setBusy(false) }
  }
  return <section className="delete-panel">
    {!confirming ? <button className="secondary" onClick={() => setConfirming(true)}>{resultId ? '이 결과 삭제' : '내 질문 기록 전체 삭제'}</button> : <>
      <p>{resultId ? '이 결과와 연결된 질문 기록을 삭제해요. 삭제 후에는 복원할 수 없어요.' : '서비스 개선을 위해 보관한 내 정제 질문 기록을 모두 삭제해요. 안내 결과와 계정은 그대로 남아요.'}</p>
      <div className="actions"><button disabled={busy} onClick={() => void erase()}>삭제 확인</button><button className="secondary" disabled={busy} onClick={() => setConfirming(false)}>취소</button></div>
    </>}
    {message && <p role="status">{message}</p>}{!!error && <Feedback error={error} />}
  </section>
}

export default function History() {
  const history = useInfiniteQuery({ queryKey: ['history'], initialPageParam: null as string | null, queryFn: ({ pageParam, signal }) => getHistory(pageParam, signal), getNextPageParam: page => page.nextCursor ?? undefined, retry: false })
  if (history.isPending) return <Waiting />
  if (history.isError && !history.data) return <Feedback error={history.error} retry={() => void history.refetch()} />
  const items = history.data?.pages.flatMap(page => page.items) ?? []
  return <section className="notice member-panel"><h1>이전 결과</h1><p>로그인한 상태에서 생성한 결과를 확인할 수 있어요.</p>
    {!items.length ? <p>저장된 이전 결과가 없어요.</p> : <ul className="history-list">{items.map(item => <li key={item.id}><Link to={'/history/' + item.id}>{item.summary.symptomLabel || '증상 확인'} · {item.summary.roomLabel} · {item.summary.facilityLabel}</Link><br /><span>{statusLabels[item.status]}</span><br /><time dateTime={item.generatedAt}>{localTime(item.generatedAt)}</time> 생성 · {localTime(item.retainedUntil)}까지 보관</li>)}</ul>}
    {history.isError && <Feedback error={history.error} retry={() => void history.fetchNextPage()} />}
    {history.hasNextPage && <button className="secondary" disabled={history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>더 보기</button>}
    <DeleteRecord />
  </section>
}

export function HistoryDetail() {
  const { resultId = '' } = useParams()
  const result = useQuery({ queryKey: ['history-result', resultId], queryFn: ({ signal }) => getHistoryResult(resultId, signal), retry: false })
  if (result.isPending) return <Waiting />
  if (result.isError) return <Feedback error={result.error} retry={() => void result.refetch()} />
  return <><ResultView result={result.data} /><div className="actions"><Link to="/history">이전 결과 목록</Link><Link to="/">새 상담 시작</Link></div><DeleteRecord resultId={resultId} /></>
}
