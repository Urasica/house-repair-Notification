import { useState } from 'react'
import { useInfiniteQuery } from '@tanstack/react-query'
import { useAuth } from '../features/auth/useAuth'
import { getHistory } from '../features/survey/api'
import { localTime } from '../features/survey/time'
import { Feedback } from './Feedback'

export default function SurveyImport({ disabled, load }: { disabled: boolean; load: (id: string) => Promise<void> }) {
  const auth = useAuth()
  const [open, setOpen] = useState(false)
  const [selected, setSelected] = useState('')
  const history = useInfiniteQuery({ queryKey: ['history', auth.data?.user?.id ?? null, 'SURVEY'], enabled: open,
    initialPageParam: null as string | null, queryFn: ({ pageParam, signal }) => getHistory(pageParam, signal),
    getNextPageParam: page => page.nextCursor ?? undefined, retry: false })
  const items = history.data?.pages.flatMap(page => page.items) ?? []
  return <section aria-label="설문 불러오기">
    <button type="button" className="secondary" aria-expanded={open} aria-controls="chat-import-panel" disabled={disabled} onClick={() => setOpen(!open)}>{open ? '설문 목록 닫기' : '이전 설문 불러오기'}</button>
    {open && <div id="chat-import-panel" className="notice chat-import-panel">
      <p>선택한 설문의 주택·위치·증상·답변을 현재 대화에 복사해요.<br />추가 설명은 가져오지 않아요.</p>
      <p>다음 질문부터 선택 라벨과 검토 자료를 OpenAI에 보내 참고해요.<br />원래 설문은 바뀌지 않아요.</p>
      {history.isPending ? <p role="status">설문 결과를 찾고 있어요.</p> : history.isError ? <Feedback error={history.error} retry={() => void history.refetch()} /> : !items.length ? <p>불러올 회원 설문 결과가 없어요. 설문 없이도 바로 질문하실 수 있어요.</p> : <>
        <label htmlFor="import-survey">불러올 설문 결과</label>
        <select id="import-survey" disabled={disabled} value={selected} onChange={event => setSelected(event.target.value)}>
          <option value="">선택해 주세요</option>{items.map(item => <option key={item.id} value={item.id}>{localTime(item.generatedAt)} · {item.summary.roomLabel} · {item.summary.symptomLabel}</option>)}
        </select>
        {history.hasNextPage && <button type="button" className="secondary" disabled={disabled || history.isFetchingNextPage} onClick={() => void history.fetchNextPage()}>이전 설문 더 보기</button>}
        <button type="button" disabled={disabled || !items.some(item => item.id === selected)} onClick={() => void load(selected).then(() => setOpen(false)).catch(() => undefined)}>선택한 설문 불러오기</button>
      </>}
    </div>}
  </section>
}
