import type { components } from '../api/generated/schema'
import { localTime } from '../features/survey/time'

type Citation = components['schemas']['Citation']
const sourceLabels = { LAW_CRITERIA: '법령 기준', LH_OPERATION: '운영 자료', SAFETY_SOURCE: '안전 자료' }

function EvidenceSource({ citation }: { citation: Citation }) {
  const excerpt = citation.excerpt
  const longExcerpt = excerpt && (excerpt.length > 240 || excerpt.split('\n').length > 4)
  return <div className="evidence-source">
    <p className="evidence-source-title">{citation.title} · {citation.locator}</p>
    <p className="evidence-source-meta">{sourceLabels[citation.kind]} · {citation.use === 'RELATED' ? '참고 자료' : '안내 근거'}</p>
    <p className="record-dates">
      <span>시행일 {citation.effectiveDate ?? '미확인'}</span>
      <span>검토 <time dateTime={citation.reviewedAt}>{localTime(citation.reviewedAt)}</time></span>
      <span>검토 기한 <time dateTime={citation.reviewUntil}>{localTime(citation.reviewUntil)}</time></span>
    </p>
    {excerpt && (longExcerpt ? <details>
      <summary>원문 발췌 보기 · {citation.locator}</summary>
      <p className="source-excerpt">{excerpt}</p>
    </details> : <p className="source-excerpt">{excerpt}</p>)}
    {/^https:\/\//.test(citation.url) && <a href={citation.url} target="_blank" rel="noopener noreferrer">공식 원문 보기</a>}
  </div>
}

export function LawExplanations({ citations }: { citations: Citation[] }) {
  const explained = citations.filter(citation => citation.explanation)
  if (!explained.length) return null

  return <div className="law-explanations">{explained.map(citation => <div key={citation.chunkId}>
    <p>{citation.explanation}</p>
    <EvidenceSource citation={citation} />
  </div>)}</div>
}

export function EvidenceSources({ citations }: { citations: Citation[] }) {
  const remaining = citations.filter(citation => !citation.explanation)
  if (!remaining.length) return null

  return <section className="evidence-sources" aria-label="정보 출처">
    <h3>{remaining.length === citations.length ? '정보 출처' : '함께 참고한 자료'}</h3>
    {remaining.map(citation => <EvidenceSource key={citation.chunkId} citation={citation} />)}
  </section>
}
