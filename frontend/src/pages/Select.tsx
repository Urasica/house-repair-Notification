import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import Consultation from '../components/Consultation'
import EndConsultation from '../components/EndConsultation'
import { Feedback } from '../components/Feedback'
import { useAuth } from '../features/auth/useAuth'
import { getSession, saveContext } from '../features/survey/api'
import { identityEpoch, readPending } from '../features/survey/storage'
import type { Catalog, Context, Session, SessionRef } from '../features/survey/storage'
import { referenceIsActive } from '../features/survey/useEvaluation'
import { useRetryDelay } from '../features/survey/useRetryDelay'

function SelectForm({ session, reference, catalog }: { session: Session; reference: SessionRef; catalog: Catalog }) {
  const [context, setContext] = useState<Context>(session.context)
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)
  const guard = useRef(false)
  const delay = useRetryDelay()
  const auth = useAuth()
  const client = useQueryClient()
  const navigate = useNavigate()
  const locked = busy || delay.waiting || !!readPending(reference.id)
  function select(field: 'housingType' | 'roomId' | 'facilityId' | 'symptomId', value: string) {
    setContext(previous => {
      const next = { ...previous, [field]: value || null } as Context
      if (next.facilityId && !catalog.facilities.find(item => item.id === next.facilityId)?.roomIds.includes(next.roomId ?? '')) next.facilityId = null
      if (next.symptomId && !catalog.symptoms.find(item => item.id === next.symptomId)?.facilityIds.includes(next.facilityId ?? '')) next.symptomId = null
      if (!next.facilityId || !next.symptomId) next.answers = {}
      return next
    })
  }
  async function save() {
    if (guard.current || locked) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null)
    try {
      const saved = await saveContext(reference, session, context, auth.data?.csrfToken)
      if (!referenceIsActive(reference, epoch)) return
      client.setQueryData(['session', reference.id], saved)
      void navigate('/survey')
    } catch (cause) { if (referenceIsActive(reference, epoch)) { setError(cause); delay.pause(cause) } }
    finally { guard.current = false; if (referenceIsActive(reference, epoch)) setBusy(false) }
  }
  async function reload() {
    const epoch = identityEpoch()
    try {
      const latest = await getSession(reference)
      if (referenceIsActive(reference, epoch)) { setContext(latest.context); setError(null); client.setQueryData(['session', reference.id], latest) }
    } catch (cause) { if (referenceIsActive(reference, epoch)) setError(cause) }
  }
  return <>
    <section className="notice form-panel"><h1>주택과 증상을 선택해 주세요</h1><p>확실하지 않은 항목은 선택하지 않아도 돼요. 입력이 부족하면 결과에서 추가 확인을 안내해 드려요.</p>
      {!!readPending(reference.id) && <p role="status">처리 중인 평가가 있어요. <Link to="/survey">설문 화면에서 완료 여부 확인</Link></p>}
      <form onSubmit={event => { event.preventDefault(); void save() }}>
        <fieldset disabled={locked}><legend>주택 유형</legend>{catalog.housingTypes.map(item => <label className="choice" key={item.id}><input type="radio" name="housingType" value={item.id} checked={context.housingType === item.id} onChange={() => select('housingType', item.id)} />{item.label}</label>)}</fieldset>
        <label htmlFor="room">공간</label><select id="room" value={context.roomId ?? ''} disabled={locked} onChange={event => select('roomId', event.target.value)}><option value="">선택하지 않음</option>{catalog.rooms.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
        <label htmlFor="facility">시설물</label><select id="facility" value={context.facilityId ?? ''} disabled={locked || !context.roomId} onChange={event => select('facilityId', event.target.value)}><option value="">선택하지 않음</option>{catalog.facilities.filter(item => item.roomIds.includes(context.roomId ?? '')).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
        <label htmlFor="symptom">증상</label><select id="symptom" value={context.symptomId ?? ''} disabled={locked || !context.facilityId} onChange={event => select('symptomId', event.target.value)}><option value="">선택하지 않음</option>{catalog.symptoms.filter(item => item.facilityIds.includes(context.facilityId ?? '')).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select>
        <label htmlFor="description">추가 설명 (선택)</label><textarea id="description" maxLength={1000} rows={4} disabled={locked} value={context.description} aria-describedby="description-hint" onChange={event => setContext({ ...context, description: event.target.value })} /><p id="description-hint">1,000자 이내로 작성해 주세요. 이름·주소·연락처는 적지 마세요.</p>
        <button disabled={locked} type="submit">{busy ? '저장하고 있어요' : '저장하고 설문으로'}</button>
      </form>
      {!!error && <><Feedback error={error} /><p>아직 저장하지 못한 선택은 그대로 남아 있어요. 최신 입력을 불러오면 아래 선택이 최신 입력으로 바뀌어요.</p><button className="secondary" onClick={() => void reload()}>최신 입력 불러오기</button></>}
    </section>
    <EndConsultation reference={reference} disabled={locked} />
  </>
}

export default function Select() { return <Consultation>{(session, ref, catalog) => <SelectForm key={session.id} session={session} reference={ref} catalog={catalog} />}</Consultation> }
