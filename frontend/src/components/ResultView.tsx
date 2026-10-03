import type { Guidance } from '../features/survey/storage'
import { localTime } from '../features/survey/time'
import { statusLabels } from '../features/survey/status'


export default function ResultView({ result }: { result: Guidance }) {
  return <article className="notice result-view">
    <p className="eyebrow">안내 결과</p><h1>{statusLabels[result.status]}</h1>
    {!result.isCurrent && <p className="past-note">과거 결과예요. 현재 입력이나 기준과 다를 수 있어요.</p>}
    <p>{result.savedToHistory ? '계정의 이전 결과에 저장됐어요.' : '현재 익명 상담에 저장됐어요. 로그인 계정의 이전 결과로 이전되지 않아요.'}</p>
    <p><time dateTime={result.generatedAt}>{localTime(result.generatedAt)}</time> 생성 · {localTime(result.retainedUntil)}까지 보관</p>
    <dl className="summary"><dt>주택</dt><dd>{result.summary.housingLabel}</dd><dt>공간·시설물</dt><dd>{result.summary.roomLabel} · {result.summary.facilityLabel}</dd><dt>증상</dt><dd>{result.summary.symptomLabel}</dd></dl>
    {result.summary.description && <p className="user-description">입력한 내용: {result.summary.description}</p>}
    {!!result.summary.answerLabels.length && <ul>{result.summary.answerLabels.map((answer, index) => <li key={index}>{answer}</li>)}</ul>}
    <h2>안내 내용</h2><ul>{result.guidance.map((text, index) => <li key={index}>{text}</li>)}</ul>
    {!!result.checks.length && <><h2>확인할 내용</h2><ul>{result.checks.map((text, index) => <li key={index}>{text}</li>)}</ul></>}
    {!!result.followUpQuestions.length && <><h2>추가 확인</h2><ul>{result.followUpQuestions.map((text, index) => <li key={index}>{text}</li>)}</ul></>}
    {!!result.citations.length && <><h2>정보 출처</h2><ul>{result.citations.map(citation => <li key={citation.chunkId}>{citation.kind === 'LAW_CRITERIA' ? '법령 기준' : citation.kind === 'LH_OPERATION' ? '운영 자료' : '안전 자료'} · {citation.use === 'RELATED' ? '참고 자료' : '안내 근거'}<br />{/^https:\/\//.test(citation.url) ? <a href={citation.url} target="_blank" rel="noopener noreferrer">{citation.title} · {citation.locator}</a> : citation.title}</li>)}</ul></>}
    <h2>직접 문의할 내용</h2><p className="contact-draft">{result.contactDraft}</p><p>{result.disclaimer}</p>
  </article>
}
