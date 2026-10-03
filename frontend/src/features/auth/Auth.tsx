import { Link, useLocation } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { useAuth } from './useAuth'

export function MemberOnly({ children }: { children: React.ReactNode }) {
  const auth = useAuth()
  const location = useLocation()
  if (auth.isPending) return <section className="notice" aria-live="polite">로그인 정보를 확인하고 있어요.</section>
  if (auth.isError && !(auth.error instanceof ApiError && auth.error.status === 401)) {
    return <section className="notice" role="alert"><p>로그인 정보를 확인하지 못했어요.</p><button onClick={() => void auth.refetch()}>다시 확인하기</button></section>
  }
  if (!auth.data?.user || auth.isError) return <section className="notice"><h2>로그인 후 이용해 주세요</h2><p>챗봇과 이전 결과는 로그인한 회원만 이용할 수 있어요.</p><Link className="button-link" to="/login" state={{ returnTo: location.pathname }}>로그인하기</Link></section>
  return children
}
