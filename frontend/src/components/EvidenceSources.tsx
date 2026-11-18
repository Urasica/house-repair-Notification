import type { components } from '../api/generated/schema'
import { localTime } from '../features/survey/time'

type Citation = components['schemas']['Citation']
const sourceLabels = { LAW_CRITERIA: '법령 기준', LH_OPERATION: '운영 자료', SAFETY_SOURCE: '안전 자료' }

function SourceDetails({ citation }: { citation: Citation }) {
  return <details className="evidence-source">
    <summary>{citation.explanation ? `근거 보기 · ${citation.locator}` : `${citation.title} · ${citation.locator}`}</summary>
    {citation.explanation && <p className="evidence-source-title">{citation.title}</p>}
    {citation.excerpt && <p className="source-excerpt">{citation.excerpt}</p>}
    <p className="evidence-source-meta">{sourceLabels[citation.kind]} · {citation.use === 'RELATED' ? '참고 자료' : '안내 근거'} · 시행일 {citation.effectiveDate ?? '미확인'} · 검토 {localTime(citation.reviewedAt)} · 검토 기한 {localTime(citation.reviewUntil)}</p>
    {/^https:\/\//.test(citation.url) && <a href={citation.url} target="_blank" rel="noopener noreferrer">공식 원문 보기</a>}
  </details>
}

export function LawExplanations({ citations }: { citations: Citation[] }) {
  const explained = citations.filter(citation => citation.explanation)
  if (!explained.length) return null

  return <div className="law-explanations">{explained.map(citation => <div key={citation.chunkId}>
    <p>{citation.explanation}</p>
    <SourceDetails citation={citation} />
  </div>)}</div>
}

export function EvidenceSources({ citations }: { citations: Citation[] }) {
  const remaining = citations.filter(citation => !citation.explanation)
  if (!remaining.length) return null

  return <details>
    <summary>{remaining.length === citations.length ? '정보 출처' : '함께 참고한 자료'}</summary>
    <div role="group" aria-label="정보 출처">
      {remaining.map(citation => <SourceDetails key={citation.chunkId} citation={citation} />)}
    </div>
  </details>
}
