import { useEffect, useState } from 'react'
import { ApiError } from '../../api/client'

export function useRetryDelay() {
  const [deadline, setDeadline] = useState(0)
  useEffect(() => {
    if (!deadline) return
    const timer = setTimeout(() => setDeadline(0), Math.max(0, deadline - Date.now()))
    return () => clearTimeout(timer)
  }, [deadline])
  return { waiting: deadline !== 0, pause(error: unknown) {
    if (!(error instanceof ApiError)) return
    const milliseconds = Number(error.details.retryAfterMs ?? (error.retryAfter ? error.retryAfter * 1000 : 0))
    if (milliseconds > 0) setDeadline(Date.now() + milliseconds)
  } }
}
