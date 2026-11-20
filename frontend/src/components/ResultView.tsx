import type { ReactNode } from 'react'
import type { Guidance } from '../features/survey/storage'
import { localTime } from '../features/survey/time'
import { statusLabels } from '../features/survey/status'
import SurveyProgress from './SurveyProgress'
import RepairExamples from './RepairExamples'
import { EvidenceSources, LawExplanations } from './EvidenceSources'
import ContactDraft from './ContactDraft'


export default function ResultView({ result, controls, actions, retryControls }: {
  result: Guidance; controls?: ReactNode; actions: ReactNode; retryControls?: ReactNode
}) {
  const unavailable = result.status === 'GUIDANCE_UNAVAILABLE'
  return <><SurveyProgress step={3} controls={controls} /><article className="notice result-view">
    <h1>{statusLabels[result.status]}</h1>
    {!result.isCurrent && <p className="past-note">과거 결과예요.<br />현재 입력이나 기준과 다를 수 있어요.</p>}
    {unavailable ? <div className="guidance-unavailable">
      {result.guidance.map((text, index) => <p key={index}>{text}</p>)}
    </div> : <>
      <h2>지금 할 일</h2>
      <ul>{result.guidance.map((text, index) => <li key={index}>{text}</li>)}</ul>
    </>}
    <nav className="actions result-actions" aria-label="설문 작업">{retryControls}{unavailable && <a className="button-link secondary" href="#contact-heading">문의 내용 보기·복사</a>}{actions}</nav>
    {!!result.checks.length && <><h2>확인할 내용</h2><ul>{result.checks.map((text, index) => <li key={index}>{text}</li>)}</ul></>}
    {!!result.followUpQuestions.length && <><h2>추가 확인</h2><ul>{result.followUpQuestions.map((text, index) => <li key={index}>{text}</li>)}</ul></>}
    {result.citations.some(citation => citation.explanation) && <>
      <h2>관련 기준에서는 이렇게 살펴봐요</h2>
      <LawExplanations citations={result.citations} />
    </>}
    <RepairExamples examples={result.referenceExamples} />
    <ContactDraft key={result.id} result={result} />
    <p>{result.disclaimer}</p>
    <section aria-label="입력한 내용과 설문 답변">
      <h2>입력한 내용과 설문 답변</h2>
      <dl className="summary"><dt>주택</dt><dd>{result.summary.housingLabel}</dd><dt>공간·시설물</dt><dd>{result.summary.roomLabel} · {result.summary.facilityLabel}</dd><dt>증상</dt><dd>{result.summary.symptomLabel}</dd></dl>
      {result.summary.description && <p className="user-description"><strong>추가 설명</strong><br />{result.summary.description}</p>}
      {!!result.summary.answerLabels.length && <ul>{result.summary.answerLabels.map((answer, index) => <li key={index}>{answer}</li>)}</ul>}
    </section>
    <EvidenceSources citations={result.citations} />
    <section aria-label="저장 위치와 보관 기간">
      <h2>저장 위치와 보관 기간</h2>
      {result.savedToHistory ? <p>계정의 이전 결과에 저장됐어요.</p> : <>
        <p>현재 익명 상담에 저장됐어요.<br />이 창에서 상담이 만료되기 전까지 다시 볼 수 있어요.<br />로그인하거나 창을 닫기 전에 필요한 내용을 복사해 주세요.</p>
        <p>로그인해도 계정으로 옮겨지지 않아요.<br />아래 보관 기한은 서버에서 기록을 정리하는 기준이에요.</p>
      </>}
      <p className="record-dates">
        <span>생성 <time dateTime={result.generatedAt}>{localTime(result.generatedAt)}</time></span>
        <span>보관 기한 <time dateTime={result.retainedUntil}>{localTime(result.retainedUntil)}</time></span>
      </p>
    </section>
  </article></>
}
