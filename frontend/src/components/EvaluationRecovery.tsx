import type { useEvaluation } from '../features/survey/useEvaluation'

export default function EvaluationRecovery({ evaluation }: { evaluation: ReturnType<typeof useEvaluation> }) {
  return <div className="recovery-panel">
    <p role="status">{evaluation.busy ? '안내 결과를 확인하고 있어요.' : '안내 요청이 남아 있어요. 결과가 나왔는지 먼저 확인해 주세요.'}</p>
    <div className="actions">
      <button type="button" disabled={evaluation.busy || evaluation.waiting} onClick={() => void evaluation.recover()}>완료 여부 확인</button>
      <button type="button" className="secondary" disabled={evaluation.busy || evaluation.waiting} onClick={evaluation.resend}>같은 요청 다시 보내기</button>
    </div>
  </div>
}
