import type { ReactNode } from 'react'

export default function SurveyProgress({ step, controls }: { step: 1 | 2 | 3; controls?: ReactNode }) {
  return <div className="survey-navigation"><ol className="survey-progress" aria-label="설문 진행 단계">
    {['증상 선택', '간단 설문', '안내 결과'].map((label, index) => <li key={label} aria-current={step === index + 1 ? 'step' : undefined} className={step > index + 1 ? 'complete' : ''}>
      <span className="step-number" aria-hidden="true">{index + 1}</span><span>{label}</span>
    </li>)}
  </ol>{controls}</div>
}
