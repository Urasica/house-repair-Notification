import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Feedback, NeedSession, Waiting } from '../components/Feedback'
import EndConsultation from '../components/EndConsultation'
import ResultView from '../components/ResultView'
import { getHistoryResult, getResult } from '../features/survey/api'
import { useSurvey } from '../features/survey/useSurvey'

export default function Result() {
  const { resultId = '' } = useParams()
  const { auth, reference } = useSurvey()
  const member = !!auth.data?.user
  const result = useQuery({ queryKey: reference ? ['result', reference.id, resultId] : ['history-result', resultId],
    queryFn: ({ signal }) => member ? getHistoryResult(resultId, signal) : getResult(reference!, resultId, signal), enabled: !auth.isPending && !auth.isError && (member || !!reference), retry: false })
  if (auth.isPending) return <Waiting />
  if (auth.isError) return <Feedback error={auth.error} retry={() => void auth.refetch()} />
  if (!member && !reference) return <NeedSession />
  if (result.isError) return <Feedback error={result.error} retry={() => void result.refetch()} />
  if (result.isPending) return <Waiting />
  return <><ResultView result={result.data} /><div className="actions">{reference && <Link className="button-link" to="/select">입력 수정</Link>}<Link className="button-link secondary" to="/">새 상담 시작</Link>{member && <Link to="/history">이전 결과 보기</Link>}</div>{reference && <EndConsultation reference={reference} />}</>
}
