export default function RepairExamples({ examples }: { examples?: string[] }) {
  if (!examples?.length) return null
  return <section className="repair-examples" aria-label="보수 검토 예시">
    <h3>이런 경우에는 보수를 검토할 수 있어요</h3>
    <p>비슷한 상황을 이해하기 위한 가상 예시예요.<br />실제 처리 이력이나 보수 승인을 뜻하지 않으며, 보수 방법과 비용은 현장 확인에 따라 달라질 수 있어요.</p>
    <ul>{examples.map((example, index) => <li key={index}>{example}</li>)}</ul>
    <p>예시와 같은지 잘 모르셔도 괜찮아요.<br />어떤 증상이 언제부터 있었는지 알려 주시면 확인에 도움이 돼요.</p>
  </section>
}
