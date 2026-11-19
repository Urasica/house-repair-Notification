import { useStartSurvey } from '../features/survey/useStartSurvey'
import { Feedback } from './Feedback'

export default function NewSurveyButton({ disabled = false }: { disabled?: boolean }) {
  const { auth, catalog, busy, error, start } = useStartSurvey()
  return <>
    <button type="button" className="secondary" disabled={disabled || !catalog.data || busy || auth.isPending || auth.isError} onClick={() => void start()}>{busy ? '설문을 시작하고 있어요' : '새 설문 시작'}</button>
    {catalog.isError && <Feedback error={catalog.error} retry={() => void catalog.refetch()} />}
    {!!error && <Feedback error={error} />}
  </>
}
