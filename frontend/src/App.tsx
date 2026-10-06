import { useState } from 'react'
import { Link, NavLink, Route, Routes, useNavigate } from 'react-router-dom'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError } from './api/client'
import { logout } from './features/auth/api'
import { MemberOnly } from './features/auth/Auth'
import { useAuth } from './features/auth/useAuth'
import { anonymous, replaceAuth } from './features/auth/state'
import Home from './pages/Home'
import Login from './pages/Login'
import Select from './pages/Select'
import Survey from './pages/Survey'
import Result from './pages/Result'
import Chat from './pages/Chat'
import History, { HistoryDetail } from './pages/History'

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
        <NavLink to="/chat">챗봇</NavLink><NavLink to="/history">이전 결과</NavLink>
        {auth.data?.user && !auth.isError ? <button className="nav-button" disabled={leaving} onClick={() => void leave()}>로그아웃</button> : <NavLink to="/login">로그인</NavLink>}
      </nav>
    </header>
    {message && <p role="alert">{message}</p>}
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/login" element={<Login />} />
      <Route path="/select" element={<Select />} />
      <Route path="/survey" element={<Survey />} />
      <Route path="/result/:resultId" element={<Result />} />
      <Route path="/chat" element={<MemberOnly><Chat /></MemberOnly>} />
      <Route path="/history" element={<MemberOnly><History /></MemberOnly>} />
      <Route path="/history/:resultId" element={<MemberOnly><HistoryDetail /></MemberOnly>} />
      <Route path="*" element={<section className="notice"><h1>페이지를 찾을 수 없어요</h1><Link to="/">홈으로 돌아가기</Link></section>} />
    </Routes>
    <footer>실제 보수 여부는 담당 기관 확인이 필요해요.</footer>
  </main>
}
