import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { Feedback, NeedSession, Waiting } from '../components/Feedback'
import EndConsultation from '../components/EndConsultation'
import ResultView from '../components/ResultView'
import HousingHelp from '../components/HousingHelp'
import { getHistoryResult, getResult } from '../features/survey/api'
import { useSurvey } from '../features/survey/useSurvey'

export default function Result() {
  const { resultId = '' } = useParams()
  const { auth, reference, query: session } = useSurvey()
  const member = !!auth.data?.user
  const result = useQuery({ queryKey: reference ? ['result', reference.id, resultId, auth.data?.user?.id ?? null, 'SURVEY'] : ['history-result', resultId, auth.data?.user?.id ?? null, 'SURVEY'],
    queryFn: ({ signal }) => member ? getHistoryResult(resultId, signal) : getResult(reference!, resultId, signal), enabled: !auth.isPending && !auth.isError && (member || !!reference), retry: false })
  if (auth.isPending) return <Waiting />
  if (auth.isError) return <Feedback error={auth.error} retry={() => void auth.refetch()} />
  if (!member && !reference) return <NeedSession />
  if (result.isError) return <Feedback error={result.error} retry={() => void result.refetch()} />
  if (result.isPending) return <Waiting />
  const context = session.data?.id === result.data.sessionId ? session.data.context : null
  const fixAnswers = result.data.reasonCodes.includes('MISSING_INPUT') && context?.housingType && context.housingType !== 'UNKNOWN' && context.roomId && context.facilityId && context.symptomId
  return <><ResultView result={result.data} />{result.data.status === 'NEED_MORE_INFO' && result.data.followUpQuestions.includes('주택 유형을 확인해 주세요.') && <HousingHelp />}<div className="actions">{reference && <Link className="button-link" to={fixAnswers ? '/survey' : '/select'} state={{ focusMissing: !!fixAnswers }}>{fixAnswers ? '설문 답변 확인' : '입력 수정'}</Link>}<Link className="button-link secondary" to="/">새 상담 시작</Link>{member && <Link className="button-link secondary" to="/history">이전 결과 보기</Link>}</div>{reference && <EndConsultation reference={reference} />}</>
}
