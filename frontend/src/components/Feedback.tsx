import { Link } from 'react-router-dom'
import { ApiError } from '../api/client'

export function Feedback({ error, retry }: { error: unknown; retry?: () => void }) {
  const code = error instanceof ApiError ? error.code : undefined
  const message = error instanceof ApiError ? error.message : '연결하지 못했어요. 저장 여부를 확인한 뒤 다시 시도해 주세요.'
  return <section className="notice error-panel" role="alert"><p>{message}</p>
    {(code === 'AUTH_REQUIRED' || code === 'AUTH_EXPIRED') ? <Link to="/login">로그인하기</Link> : <Link to="/">홈으로 돌아가기</Link>}
    {retry && <button className="secondary" onClick={retry}>다시 확인하기</button>}
  </section>
}

export function Waiting() { return <p role="status">정보를 확인하고 있어요.</p> }
export function NeedSession() { return <section className="notice"><h1>새 상담을 시작해 주세요</h1><p>상담이 없거나 만료·종료됐어요. 홈에서 새 설문을 시작할 수 있어요.</p><Link to="/">홈으로 돌아가기</Link></section> }
