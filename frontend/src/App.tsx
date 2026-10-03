import { useState } from 'react'
import { Link, Route, Routes, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from './api/client'
import { logout } from './features/auth/api'
import { MemberOnly } from './features/auth/Auth'
import { useAuth } from './features/auth/useAuth'
import { anonymous, replaceAuth } from './features/auth/state'
import Home from './pages/Home'
import Login from './pages/Login'

export default function App() {
  const auth = useAuth()
  const client = useQueryClient()
  const navigate = useNavigate()
  const [message, setMessage] = useState('')
  const [leaving, setLeaving] = useState(false)
  async function leave() {
    if (!auth.data?.csrfToken) return
    setLeaving(true)
    try {
      await logout(auth.data.csrfToken)
    } catch (error) {
      if (!(error instanceof ApiError && error.status === 401)) {
        setMessage('로그아웃하지 못했어요. 잠시 후 다시 시도해 주세요.')
        setLeaving(false)
        return
      }
    }
    await replaceAuth(client, anonymous)
    setLeaving(false)
    setMessage('')
    void navigate('/', { replace: true })
  }
  return <main className="shell">
    <header className="topbar">
      <Link className="brand" to="/"><span className="brand-mark" aria-hidden="true">⌂</span> 우리집 보수 길잡이</Link>
      <nav aria-label="이용 메뉴">
        <Link to="/chat">챗봇</Link><Link to="/history">이전 결과</Link>
        {auth.data?.user && !auth.isError ? <button className="nav-button" disabled={leaving} onClick={() => void leave()}>로그아웃</button> : <Link to="/login">로그인</Link>}
      </nav>
    </header>
    {message && <p role="alert">{message}</p>}
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/chat" element={<MemberOnly><section className="notice member-panel"><h1>회원 챗봇</h1><p>검토된 안내 자료와 대화 기능을 준비하고 있어요.</p></section></MemberOnly>} />
      <Route path="/history" element={<MemberOnly><section className="notice member-panel"><h1>이전 결과</h1><p>이전 결과 조회 기능을 준비하고 있어요.</p></section></MemberOnly>} />
      <Route path="/history/:resultId" element={<MemberOnly><section className="notice member-panel"><h1>이전 결과 상세</h1><p>조회 기능을 준비하고 있어요.</p></section></MemberOnly>} />
      <Route path="*" element={<section className="notice"><h1>페이지를 찾을 수 없어요</h1><Link to="/">홈으로 돌아가기</Link></section>} />
    </Routes>
    <footer>실제 보수 여부는 담당 기관 확인이 필요해요.</footer>
  </main>
}
