import { useEffect, useId, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { useAuth } from '../features/auth/useAuth'
import { endSession } from '../features/survey/api'
import { clearSession, identityEpoch } from '../features/survey/storage'
import type { SessionRef } from '../features/survey/storage'
import { referenceIsActive } from '../features/survey/useEvaluation'
import { Feedback } from './Feedback'

export default function EndConsultation({ reference, disabled = false }: { reference: SessionRef; disabled?: boolean }) {
  const auth = useAuth()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [confirming, setConfirming] = useState(false)
  const [erase, setErase] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  const guard = useRef(false)
  const trigger = useRef<HTMLButtonElement>(null)
  const cancel = useRef<HTMLButtonElement>(null)
  const descriptionId = useId()
  useEffect(() => { if (confirming) cancel.current?.focus() }, [confirming])
  async function end() {
    if (guard.current) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null)
    try {
      await endSession(reference, auth.data?.csrfToken, erase)
      if (!referenceIsActive(reference, epoch)) return
      const surveyQueries = { predicate: (query: { queryKey: readonly unknown[] }) => ['session', 'result', 'questions'].includes(String(query.queryKey[0])) && query.queryKey[1] === reference.id }
      await client.cancelQueries(surveyQueries)
      if (!referenceIsActive(reference, epoch)) return
      client.removeQueries(surveyQueries)
      clearSession(reference)
      void navigate('/', { replace: true })
    } catch (cause) { if (referenceIsActive(reference, epoch)) setError(cause) }
    finally { guard.current = false; if (referenceIsActive(reference, epoch)) setBusy(false) }
  }
  return <section className="end-panel" aria-label="설문 상담 관리">
    <button ref={trigger} type="button" className="secondary" disabled={disabled || busy} aria-expanded={confirming} onClick={() => setConfirming(!confirming)}>상담 종료</button>
    {confirming && <div className="notice end-confirmation" role="group" aria-label="상담 종료 확인">
      <p id={descriptionId}>{reference.mode === 'MEMBER' ? '상담을 종료해도 저장한 결과와 질문 기록은 계정에 남아요.'
        : <>상담을 종료하면 결과와 입력한 설명은 삭제돼요.<br />정제된 질문 항목은 향후 서비스 개선을 위해 보관돼요.</>}</p>
      {reference.mode === 'GUEST' && <label className="choice"><input type="checkbox" checked={erase} disabled={busy} onChange={event => setErase(event.target.checked)} /> 정제된 질문 기록도 삭제</label>}
      <div className="actions"><button className="danger" disabled={busy || disabled} onClick={() => void end()}>종료 확인</button><button ref={cancel} className="secondary" aria-describedby={descriptionId} disabled={busy} onClick={() => { setConfirming(false); trigger.current?.focus() }}>취소</button></div>
      {!!error && <Feedback error={error} />}
    </div>}
  </section>
}
