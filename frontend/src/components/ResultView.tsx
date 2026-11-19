import { useState } from 'react'
import type { ReactNode } from 'react'
import type { Guidance } from '../features/survey/storage'
import { localTime } from '../features/survey/time'
import { statusLabels } from '../features/survey/status'
import SurveyProgress from './SurveyProgress'
import RepairExamples from './RepairExamples'
import { EvidenceSources, LawExplanations } from './EvidenceSources'


export default function ResultView({ result, controls, actions }: { result: Guidance; controls?: ReactNode; actions: ReactNode }) {
  const [copyMessage, setCopyMessage] = useState('')
  const [copyFailed, setCopyFailed] = useState(false)
  const unavailable = result.status === 'GUIDANCE_UNAVAILABLE'
  const inquiry = [`주택: ${result.summary.housingLabel}`, `위치: ${result.summary.roomLabel} · ${result.summary.facilityLabel}`, `증상: ${result.summary.symptomLabel}`, ...result.summary.answerLabels, result.contactDraft].join('\n')
  async function copy() {
    try {
      await navigator.clipboard.writeText(inquiry)
      setCopyFailed(false); setCopyMessage('문의 내용을 복사했어요.')
    } catch { setCopyFailed(true); setCopyMessage('자동으로 복사하지 못했어요. 아래 내용을 선택해 직접 복사해 주세요.') }
  }
  return <><SurveyProgress step={3} controls={controls} /><article className="notice result-view">
    <p className="eyebrow">안내 결과</p><h1>{statusLabels[result.status]}</h1>
    {!result.isCurrent && <p className="past-note">과거 결과예요. 현재 입력이나 기준과 다를 수 있어요.</p>}
    {unavailable ? <p className="guidance-unavailable">{result.guidance.join(' ')}</p> : <>
      <h2>지금 할 일</h2>
      <ul>{result.guidance.map((text, index) => <li key={index}>{text}</li>)}</ul>
    </>}
    <nav className="actions result-actions" aria-label="설문 작업">{actions}</nav>
    {!!result.checks.length && <><h2>확인할 내용</h2><ul>{result.checks.map((text, index) => <li key={index}>{text}</li>)}</ul></>}
    {!!result.followUpQuestions.length && <><h2>추가 확인</h2><ul>{result.followUpQuestions.map((text, index) => <li key={index}>{text}</li>)}</ul></>}
    {result.citations.some(citation => citation.explanation) && <>
      <h2>관련 기준에서는 이렇게 살펴봐요</h2>
      <LawExplanations citations={result.citations} />
    </>}
    <RepairExamples examples={result.referenceExamples} />
    <h2>직접 문의할 내용</h2><p className="contact-draft">{inquiry}</p><button type="button" className="secondary" onClick={() => void copy()}>문의 내용 복사</button>
    <p role="status">{copyMessage}</p>{copyFailed && <textarea className="copy-text" aria-label="복사할 문의 내용" readOnly autoFocus rows={6} value={inquiry} onFocus={event => event.target.select()} />}
    <p>{result.disclaimer}</p>
    <p>{result.savedToHistory ? '로그인한 계정의 ‘이전 결과’에서 다시 볼 수 있어요.' : '비회원 결과예요. 현재 창에서 상담이 만료되기 전까지 이어볼 수 있어요. 로그인하거나 창을 닫기 전에 필요한 내용을 복사해 주세요.'}</p>
    <details><summary>입력한 내용과 설문 답변</summary>
      <dl className="summary"><dt>주택</dt><dd>{result.summary.housingLabel}</dd><dt>공간·시설물</dt><dd>{result.summary.roomLabel} · {result.summary.facilityLabel}</dd><dt>증상</dt><dd>{result.summary.symptomLabel}</dd></dl>
      {result.summary.description && <p className="user-description">입력한 내용: {result.summary.description}</p>}
      {!!result.summary.answerLabels.length && <ul>{result.summary.answerLabels.map((answer, index) => <li key={index}>{answer}</li>)}</ul>}
    </details>
    <EvidenceSources citations={result.citations} />
    <details><summary>저장 위치와 보관 기간</summary>
      <p>{result.savedToHistory ? '계정의 이전 결과에 저장됐어요.' : '현재 익명 상담에 저장됐어요. 로그인 계정의 이전 결과로 이전되지 않아요.'}</p>
      {!result.savedToHistory && <p>아래 보관 기한은 서버에서 기록을 정리하는 기준이에요. 이 창에서 결과를 다시 열 수 있는 상담 이용 시간과는 달라요.</p>}
      <p><time dateTime={result.generatedAt}>{localTime(result.generatedAt)}</time> 생성 · {localTime(result.retainedUntil)}까지 보관</p>
    </details>
  </article></>
}
