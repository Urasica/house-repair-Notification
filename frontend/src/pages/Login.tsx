import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { useQueryClient } from '@tanstack/react-query'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { ApiError } from '../api/client'
import { login, register, type Credentials } from '../features/auth/api'
import { useAuth } from '../features/auth/useAuth'
import { replaceAuth, safeReturnPath } from '../features/auth/state'

export default function Login() {
  const [joining, setJoining] = useState(false)
  const [message, setMessage] = useState('')
  const auth = useAuth()
  const client = useQueryClient()
  const navigate = useNavigate()
  const location = useLocation()
  const form = useForm<Credentials>()

  async function submit(values: Credentials) {
    setMessage('')
    try {
      if (joining) {
        await register(values)
        form.reset({ email: values.email, password: '' })
        setJoining(false)
        setMessage('가입했어요. 비밀번호를 다시 입력해 로그인해 주세요.')
      } else {
        await replaceAuth(client, await login(values))
        form.reset({ email: '', password: '' })
        void navigate(safeReturnPath((location.state as { returnTo?: unknown } | null)?.returnTo), { replace: true })
      }
    } catch (error) {
      setMessage(error instanceof ApiError ? error.message : '연결하지 못했어요. 잠시 후 다시 시도해 주세요.')
      form.resetField('password')
    }
  }

  if (auth.data?.user && !auth.isError) return <section className="notice"><h2>로그인되어 있어요</h2><Link to="/">홈으로 돌아가기</Link></section>
  return <section className="notice auth-panel" aria-labelledby="auth-title">
    <h1 id="auth-title">{joining ? '회원가입' : '로그인'}</h1>
    <p>챗봇과 본인의 이전 결과를 확인할 수 있어요.</p>
    <form onSubmit={form.handleSubmit(submit)}>
      <label htmlFor="email">이메일</label>
      <input id="email" type="email" autoComplete="username" maxLength={254} aria-invalid={!!form.formState.errors.email} aria-describedby="email-error" {...form.register('email', { required: '이메일을 입력해 주세요.', maxLength: 254 })} />
      <span id="email-error" className="field-error">{form.formState.errors.email?.message}</span>
      <label htmlFor="password">비밀번호</label>
      <input id="password" type="password" autoComplete={joining ? 'new-password' : 'current-password'} maxLength={128} aria-invalid={!!form.formState.errors.password} aria-describedby="password-hint password-error" {...form.register('password', { required: '비밀번호를 입력해 주세요.', minLength: { value: 12, message: '12자 이상 입력해 주세요.' }, maxLength: 128 })} />
      <span id="password-hint">12~128자로 입력해 주세요.</span>
      <span id="password-error" className="field-error">{form.formState.errors.password?.message}</span>
      <p role="status">{message}</p>
      <button type="submit" disabled={form.formState.isSubmitting}>{form.formState.isSubmitting ? '처리 중…' : joining ? '가입하기' : '로그인하기'}</button>
      <button type="button" className="secondary" disabled={form.formState.isSubmitting} onClick={() => { setJoining(!joining); setMessage(''); form.resetField('password') }}>{joining ? '로그인으로 돌아가기' : '회원가입'}</button>
    </form>
  </section>
}
