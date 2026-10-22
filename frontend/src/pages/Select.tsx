import { useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import Consultation from '../components/Consultation'
import EndConsultation from '../components/EndConsultation'
import SelectionSummary from '../components/SelectionSummary'
import SurveyProgress from '../components/SurveyProgress'
import { facilitiesForRoom, facilityLabel, updateSelection } from '../features/survey/presentation'
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
  const room = catalog.rooms.find(item => item.id === context.roomId)
  const facilities = facilitiesForRoom(catalog, context.roomId)
  const previousFacility = catalog.facilities.find(item => item.id === context.facilityId && !facilities.some(option => option.id === item.id))
  function select(field: 'housingType' | 'roomId' | 'facilityId' | 'symptomId', value: string) {
    setContext(previous => updateSelection(previous, field, value))
  }
  async function save() {
    if (guard.current || locked) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null)
    try {
      const saved = await saveContext(reference, session, context, auth.data?.csrfToken)
      if (!referenceIsActive(reference, epoch)) return
      client.setQueryData(['session', reference.id, auth.data?.user?.id ?? null, 'SURVEY'], saved)
      void navigate('/survey')
    } catch (cause) { if (referenceIsActive(reference, epoch)) { setError(cause); delay.pause(cause) } }
    finally { guard.current = false; if (referenceIsActive(reference, epoch)) setBusy(false) }
  }
  async function reload() {
    const epoch = identityEpoch()
    try {
      const latest = await getSession(reference)
      if (referenceIsActive(reference, epoch)) { setContext(latest.context); setError(null); client.setQueryData(['session', reference.id, auth.data?.user?.id ?? null, 'SURVEY'], latest) }
    } catch (cause) { if (referenceIsActive(reference, epoch)) setError(cause) }
  }
  return <>
    <SurveyProgress step={1} />
    <div className="consultation-layout">
    <section className="notice form-panel"><p className="eyebrow">01 · 주택과 증상</p><h1>어디가 불편한가요?</h1><p>공간을 먼저 고르면, 그곳에 맞는 시설물과 증상을 차례로 선택할 수 있어요.</p>
      {!!readPending(reference.id) && <p role="status">처리 중인 평가가 있어요. <Link to="/survey">설문 화면에서 완료 여부 확인</Link></p>}
      <form onSubmit={event => { event.preventDefault(); void save() }}>
        <fieldset className="housing-options" disabled={locked}><legend>주택 유형</legend>{catalog.housingTypes.map(item => <label className="choice" key={item.id}><input type="radio" name="housingType" value={item.id} checked={context.housingType === item.id} onChange={() => select('housingType', item.id)} />{item.label}</label>)}</fieldset>
        <div className="selection-group"><span className="field-step" aria-hidden="true">1</span><div><label htmlFor="room">공간</label><p className="field-hint">불편한 곳이 어디인가요?</p><select id="room" value={context.roomId ?? ''} disabled={locked} onChange={event => select('roomId', event.target.value)}><option value="">선택하지 않음</option>{catalog.rooms.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></div></div>
        <div className="selection-group"><span className="field-step" aria-hidden="true">2</span><div><label htmlFor="facility">시설물</label><p className="field-hint" id="facility-hint">{room ? `${room.label}에 있는 어떤 부분인가요?` : '공간을 먼저 선택해 주세요.'}</p><select id="facility" aria-describedby="facility-hint" value={context.facilityId ?? ''} disabled={locked || !context.roomId} onChange={event => select('facilityId', event.target.value)}><option value="">선택하지 않음</option>{previousFacility && <option value={previousFacility.id}>{previousFacility.label} (이전 선택)</option>}{facilities.map(item => <option key={item.id} value={item.id}>{facilityLabel(catalog, context.roomId, item.id)}</option>)}</select></div></div>
        <div className="selection-group"><span className="field-step" aria-hidden="true">3</span><div><label htmlFor="symptom">증상</label><p className="field-hint">{context.facilityId ? '어떤 불편함이 있나요?' : '시설물을 선택하면 관련 증상이 나와요.'}</p><select id="symptom" value={context.symptomId ?? ''} disabled={locked || !context.facilityId} onChange={event => select('symptomId', event.target.value)}><option value="">선택하지 않음</option>{catalog.symptoms.filter(item => item.facilityIds.includes(context.facilityId ?? '')).map(item => <option key={item.id} value={item.id}>{item.label}</option>)}</select></div></div>
        <label htmlFor="description">추가 설명 (선택)</label><textarea id="description" maxLength={1000} rows={4} disabled={locked} value={context.description} aria-describedby="description-hint" onChange={event => setContext({ ...context, description: event.target.value })} /><p id="description-hint">1,000자 이내로 작성해 주세요. 이름·주소·연락처는 적지 마세요.</p>
        <button disabled={locked} type="submit">{busy ? '저장하고 있어요' : '저장하고 설문으로'}</button>
      </form>
      {!!error && <><Feedback error={error} /><p>아직 저장하지 못한 선택은 그대로 남아 있어요. 최신 입력을 불러오면 아래 선택이 최신 입력으로 바뀌어요.</p><button className="secondary" onClick={() => void reload()}>최신 입력 불러오기</button></>}
    </section>
    <SelectionSummary catalog={catalog} context={context} />
    </div>
    <EndConsultation reference={reference} disabled={locked} />
  </>
}

export default function Select() { return <Consultation>{(session, ref, catalog) => <SelectForm key={session.id} session={session} reference={ref} catalog={catalog} />}</Consultation> }
