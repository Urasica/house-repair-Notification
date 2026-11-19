import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ApiError } from '../api/client'
import { Feedback, NeedSession, Waiting } from '../components/Feedback'
import EndConsultation from '../components/EndConsultation'
import EvaluationRecovery from '../components/EvaluationRecovery'
import ResultView from '../components/ResultView'
import HousingHelp from '../components/HousingHelp'
import NewSurveyButton from '../components/NewSurveyButton'
import { getHistoryResult, getResult } from '../features/survey/api'
import type { Guidance, Session, SessionRef } from '../features/survey/storage'
import { useEvaluation } from '../features/survey/useEvaluation'
import { useSurvey } from '../features/survey/useSurvey'

function RetryResult({ result, reference, session, userId, csrf }: {
  result: Guidance; reference: SessionRef; session: Session; userId: string | null; csrf?: string | null
}) {
  const evaluation = useEvaluation(reference, session, userId, csrf)
  const locked = evaluation.busy || !!evaluation.pending
  return <ResultView result={result} controls={<EndConsultation reference={reference} disabled={locked} />} retryControls={<>
    {evaluation.pending ? <EvaluationRecovery evaluation={evaluation} /> :
      <button type="button" disabled={evaluation.busy || evaluation.waiting} onClick={() => evaluation.start()}>입력한 내용으로 다시 시도</button>}
    {!!evaluation.error && <Feedback error={evaluation.error} />}
    {evaluation.error instanceof ApiError && evaluation.error.code === 'CONTEXT_CONFLICT' && <Link className="button-link secondary" to="/survey">최근 설문 확인</Link>}
    {evaluation.message && <p role="status">{evaluation.message}</p>}
  </>} actions={<>
    <NewSurveyButton disabled={locked} />
    {userId && <Link className="button-link secondary" to="/history">이전 결과 보기</Link>}
  </>} />
}

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
  const currentReference = reference?.id === result.data.sessionId ? reference : null
  const currentSession = session.data?.id === result.data.sessionId ? session.data : null
  const context = currentSession?.context
  const fixAnswers = result.data.reasonCodes.includes('MISSING_INPUT') && context?.housingType && context.housingType !== 'UNKNOWN' && context.roomId && context.facilityId && context.symptomId
  const retry = result.data.status === 'GUIDANCE_UNAVAILABLE'
  if (retry && currentReference && currentSession && currentSession.revision === result.data.contextRevision) {
    return <RetryResult key={result.data.id} result={result.data} reference={currentReference} session={currentSession} userId={auth.data?.user?.id ?? null} csrf={auth.data?.csrfToken} />
  }
  return <><ResultView result={result.data}
    controls={currentReference && <EndConsultation reference={currentReference} />}
    actions={<>
      {currentReference && (!retry || !session.isPending) && <Link className="button-link secondary" to={fixAnswers || retry ? '/survey' : '/select'} state={{ focusMissing: !!fixAnswers }}>{retry ? '최근 설문 확인' : fixAnswers ? '설문 답변 확인' : '입력 수정'}</Link>}
      <NewSurveyButton />
      {member && <Link className="button-link secondary" to="/history">이전 결과 보기</Link>}
    </>} />{result.data.status === 'NEED_MORE_INFO' && result.data.followUpQuestions.includes('주택 유형을 확인해 주세요.') && <HousingHelp />}</>
}
