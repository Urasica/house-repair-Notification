import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { evaluate, requestState } from './api'
import { clearPending, identityEpoch, readPending, storePending, storedReference, referenceFrom } from './storage'
import type { Guidance, Pending, Session, SessionRef } from './storage'

export function referenceIsActive(ref: SessionRef, epoch: number) {
  return identityEpoch() === epoch && referenceFrom(storedReference(ref.mode === 'MEMBER', ref.purpose), ref.mode === 'MEMBER', ref.purpose)?.id === ref.id
}

export function useEvaluation(ref: SessionRef, session: Session, userId: string | null, csrf?: string | null) {
  const client = useQueryClient()
  const navigate = useNavigate()
  const [pending, setPending] = useState<Pending | null>(() => readPending(ref.id))
  const [error, setError] = useState<unknown>(null)
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [waitUntil, setWaitUntil] = useState(0)
  const guard = useRef(false)
  useEffect(() => {
    if (!waitUntil) return
    const timer = setTimeout(() => setWaitUntil(0), Math.max(0, waitUntil - Date.now()))
    return () => clearTimeout(timer)
  }, [waitUntil])

  function finish(result: Guidance) {
    clearPending(ref.id); setPending(null)
    client.setQueryData(['result', ref.id, result.id, userId, 'SURVEY'], result)
    void client.invalidateQueries({ queryKey: ['session', ref.id] })
    void navigate('/result/' + result.id)
  }
  function terminal(deleted: boolean) {
    clearPending(ref.id); setPending(null)
    setMessage(deleted ? '이 기록은 삭제됐어요. 새 평가가 필요하면 직접 시작해 주세요.' : '평가가 완료되지 않았어요. 새 평가가 필요하면 직접 시작해 주세요.')
    if (deleted) {
      client.removeQueries({ predicate: query => ['result', 'history', 'history-result'].includes(String(query.queryKey[0])) })
      void client.invalidateQueries({ queryKey: ['session', ref.id] })
    }
  }
  function failed(cause: unknown) {
    setError(cause)
    if (cause instanceof ApiError) {
      if (cause.code === 'REQUEST_DELETED') terminal(true)
      else if (cause.code === 'REQUEST_FAILED' || cause.code === 'IDEMPOTENCY_CONFLICT' || cause.code === 'CONTEXT_CONFLICT') terminal(false)
      const delay = Number(cause.details.retryAfterMs ?? (cause.retryAfter ? cause.retryAfter * 1000 : 0))
      if (delay > 0) setWaitUntil(Date.now() + delay)
    }
  }
  async function execute(request: Pending) {
    if (guard.current || waitUntil > Date.now()) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null); setMessage('')
    try {
      const result = await evaluate(ref, request, csrf)
      if (referenceIsActive(ref, epoch)) finish(result)
    } catch (cause) { if (referenceIsActive(ref, epoch)) failed(cause) }
    finally { guard.current = false; if (referenceIsActive(ref, epoch)) setBusy(false) }
  }
  function start(saved: Session = session) {
    if (guard.current || readPending(ref.id) || waitUntil > Date.now()) return
    const request = { requestId: crypto.randomUUID(), expectedRevision: saved.revision }
    storePending(ref.id, request); setPending(request)
    void execute(request)
  }
  async function recover() {
    if (!pending || guard.current || waitUntil > Date.now()) return
    const epoch = identityEpoch()
    guard.current = true; setBusy(true); setError(null)
    try {
      const state = await requestState(ref, pending)
      if (!referenceIsActive(ref, epoch)) return
      if (state.state === 'COMPLETED' && state.kind === 'SURVEY' && state.response && 'guidance' in state.response) finish(state.response)
      else if (state.state === 'DELETED') terminal(true)
      else if (state.state === 'FAILED') terminal(false)
      else {
        setMessage('평가를 처리하고 있어요. 잠시 후 완료 여부를 확인해 주세요.')
        setWaitUntil(Date.now() + (state.retryAfterMs ?? 1000))
      }
    } catch (cause) {
      if (!referenceIsActive(ref, epoch)) return
      if (cause instanceof ApiError && cause.code === 'NOT_FOUND') setMessage('저장된 요청이 없어요. 같은 요청으로 다시 보내면 중복을 방지할 수 있어요.')
      else failed(cause)
    } finally { guard.current = false; if (referenceIsActive(ref, epoch)) setBusy(false) }
  }
  return { pending, error, message, busy, waiting: waitUntil !== 0, start, recover, resend: () => { if (pending) void execute(pending) } }
}
