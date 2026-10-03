import { useRef, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'
import Consultation from '../components/Consultation'
import EndConsultation from '../components/EndConsultation'
import { Feedback, Waiting } from '../components/Feedback'
import { useAuth } from '../features/auth/useAuth'
import { getQuestions, getSession, saveContext } from '../features/survey/api'
import type { Questions } from '../features/survey/api'
import { identityEpoch } from '../features/survey/storage'
import type { Session, SessionRef } from '../features/survey/storage'
import { referenceIsActive, useEvaluation } from '../features/survey/useEvaluation'
import { useRetryDelay } from '../features/survey/useRetryDelay'

function AnswerFields({ questions, session, locked, answer, error }: { questions: Questions; session: Session; locked: boolean; answer: (id: string, value: string) => void; error: boolean }) {
  const [draft, setDraft] = useState(session.context.answers ?? {})
  return <>{questions.questions.map(question => <fieldset key={question.questionId} disabled={locked}>
    <legend>{question.label}{question.required && <span className="required-note"> (필수 확인)</span>}</legend>
    {question.options.map(option => <label className="choice" key={option.value}><input type="radio" name={question.questionId} value={option.value} checked={draft[question.questionId] === option.value} aria-required={question.required} aria-describedby={error ? 'answer-error' : undefined} onChange={() => { setDraft({ ...draft, [question.questionId]: option.value }); answer(question.questionId, option.value) }} />{option.label}</label>)}
  </fieldset>)}</>
}

function SurveyActive({ session, reference }: { session: Session; reference: SessionRef }) {
  const auth = useAuth()
  const client = useQueryClient()
  const evaluation = useEvaluation(reference, session, auth.data?.csrfToken)
  const questions = useQuery({ queryKey: ['questions', session.id, session.revision], queryFn: ({ signal }) => getQuestions(reference, signal), retry: false, refetchOnWindowFocus: false })
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<unknown>(null)
  const guard = useRef(false)
  const delay = useRetryDelay()
  const matching = questions.data?.revision === session.revision && questions.data?.catalogVersion === session.catalogVersion
  const locked = saving || delay.waiting || evaluation.busy || !!evaluation.pending
  async function answer(id: string, value: string) {
    if (guard.current || locked || !matching) return
    const epoch = identityEpoch()
    guard.current = true; setSaving(true); setSaveError(null)
    try {
      const saved = await saveContext(reference, session, { ...session.context, answers: { ...session.context.answers, [id]: value } }, auth.data?.csrfToken)
      if (!referenceIsActive(reference, epoch)) return
      client.setQueryData(['session', reference.id], saved)
      if (questions.data!.questions.find(question => question.questionId === id)?.interruptValues?.includes(value)) evaluation.start(saved)
    } catch (cause) { if (referenceIsActive(reference, epoch)) { setSaveError(cause); delay.pause(cause) } }
    finally { guard.current = false; if (referenceIsActive(reference, epoch)) setSaving(false) }
  }
  async function reload() {
    const epoch = identityEpoch()
    try {
      const latest = await getSession(reference)
      if (!referenceIsActive(reference, epoch)) return
      client.setQueryData(['session', reference.id], latest)
      client.removeQueries({ queryKey: ['questions', reference.id] })
      setSaveError(null)
    } catch (cause) { if (referenceIsActive(reference, epoch)) setSaveError(cause) }
  }
  return <>
    <section className="notice form-panel"><h1>간단히 확인해 주세요</h1><p>선택한 답은 자동으로 저장돼요. 위험 확인 항목을 선택하면 저장 후 안내 결과를 먼저 확인해요.</p>
      {questions.isPending ? <Waiting /> : questions.isError ? <Feedback error={questions.error} retry={() => void questions.refetch()} /> : !matching ? <><p role="alert">다른 화면에서 입력이 바뀌었어요. 최신 입력을 확인해 주세요.</p><button onClick={() => void reload()}>최신 입력 불러오기</button></> : <>
        {!questions.data.questions.length && <p>현재 선택으로 확인할 질문이 없어요. 안내 결과에서 필요한 정보를 확인할 수 있어요.</p>}
        <AnswerFields key={session.revision} questions={questions.data} session={session} locked={locked} answer={(id, value) => void answer(id, value)} error={!!saveError} />
      </>}
      {saving && <p role="status">답을 저장하고 있어요.</p>}
      {!!saveError && <div id="answer-error"><Feedback error={saveError} /><p>답을 저장하지 못했어요. 최신 입력을 확인하고 다시 선택해 주세요.</p><button className="secondary" disabled={saving} onClick={() => void reload()}>최신 입력 불러오기</button></div>}
      {!!evaluation.error && <Feedback error={evaluation.error} />}
      {evaluation.error instanceof ApiError && evaluation.error.code === 'CONTEXT_CONFLICT' && <button className="secondary" onClick={() => void reload()}>최신 입력 불러오기</button>}
      {evaluation.message && <p role="status">{evaluation.message}</p>}
      {evaluation.pending ? <div className="recovery-panel"><p>평가 요청이 남아 있어요. 저장된 결과를 먼저 확인해 주세요.</p><div className="actions"><button disabled={evaluation.busy || evaluation.waiting} onClick={() => void evaluation.recover()}>완료 여부 확인</button><button className="secondary" disabled={evaluation.busy || evaluation.waiting} onClick={evaluation.resend}>같은 요청 다시 보내기</button></div></div> : <button disabled={saving || evaluation.busy || evaluation.waiting || !!saveError || !matching} onClick={() => evaluation.start()}>{evaluation.busy ? '평가하고 있어요' : evaluation.message ? '새 평가로 다시 시도' : '안내 결과 확인'}</button>}
      {!locked && <p className="continue-link"><Link to="/select">주택·증상 수정</Link></p>}
    </section>
    <EndConsultation reference={reference} disabled={locked} />
  </>
}

export default function Survey() { return <Consultation>{(session, ref) => <SurveyActive key={session.id} session={session} reference={ref} />}</Consultation> }
