import type { components } from './generated/schema'

type ErrorCode = components['schemas']['ErrorCode']

export class ApiError extends Error {
  constructor(public code: ErrorCode, message: string, public status: number, public retryAfter: number | null = null) {
    super(message)
  }
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch('/api/v1' + path, {
    ...options, credentials: 'same-origin', cache: 'no-store',
    headers: { 'Content-Type': 'application/json', ...options.headers },
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null) as components['schemas']['ErrorResponse'] | null
    const retry = response.headers.get('Retry-After')
    throw new ApiError(body?.error.code ?? 'SERVICE_UNAVAILABLE',
      body?.error.message ?? '서비스에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.',
      response.status, retry ? Number(retry) : null)
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
