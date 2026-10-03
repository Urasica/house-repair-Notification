import { afterEach, describe, expect, it, vi } from 'vitest'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { renderToStaticMarkup } from 'react-dom/server'
import { MemberOnly } from './Auth'
import { getAuth, login, logout } from './api'
import { AUTH_KEY, anonymous, replaceAuth, safeReturnPath } from './state'

afterEach(() => vi.unstubAllGlobals())

describe('account requests', () => {
  it('uses cookies and no-store without transmitting an auth token in JSON', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify(anonymous), { status: 200 }))
    vi.stubGlobal('fetch', fetcher)
    await getAuth()
    const request = fetcher.mock.calls[0][1]
    expect(request.credentials).toBe('same-origin')
    expect(request.cache).toBe('no-store')
    expect(request.body).toBeUndefined()
  })

  it('sends CSRF on logout and clears every previous account cache on identity change', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(null, { status: 204 }))
    const removeItem = vi.fn()
    vi.stubGlobal('fetch', fetcher)
    vi.stubGlobal('sessionStorage', { removeItem })
    await logout('test-only-csrf')
    expect(fetcher.mock.calls[0][1].headers['X-CSRF-Token']).toBe('test-only-csrf')
    const client = new QueryClient()
    client.setQueryData(['history', 'previous-user'], { private: 'previous-data' })
    client.setQueryData(['chat', 'previous-session'], { private: 'previous-message' })
    await replaceAuth(client, anonymous)
    expect(client.getQueryData(['history', 'previous-user'])).toBeUndefined()
    expect(client.getQueryData(['chat', 'previous-session'])).toBeUndefined()
    expect(client.getQueryData(AUTH_KEY)).toEqual(anonymous)
    expect(removeItem).toHaveBeenCalledWith('member-session-id')
  })

  it('returns a server rate-limit error without automatically retrying credentials', async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: 'RATE_LIMITED', message: '잠시 후 다시 시도해 주세요.', details: {}, traceId: 'test' },
    }), { status: 429, headers: { 'Retry-After': '60' } }))
    vi.stubGlobal('fetch', fetcher)
    await expect(login({ email: 'test@example.com', password: 'not-a-real-password' })).rejects.toMatchObject({ code: 'RATE_LIMITED', retryAfter: 60 })
    expect(fetcher).toHaveBeenCalledTimes(1)
  })
})

describe('member routes', () => {
  function renderMember(user: boolean) {
    const client = new QueryClient()
    client.setQueryData(AUTH_KEY, user ? {
      user: { id: 'test-user', email: 'test@example.com', createdAt: '2026-10-03T00:00:00Z' }, csrfToken: 'test-only',
    } : anonymous)
    return renderToStaticMarkup(<QueryClientProvider client={client}><MemoryRouter initialEntries={['/history']}><MemberOnly><p>protected-content</p></MemberOnly></MemoryRouter></QueryClientProvider>)
  }

  it('hides member content from a signed-out user', () => {
    const html = renderMember(false)
    expect(html).not.toContain('protected-content')
    expect(html).toContain('로그인 후 이용해 주세요')
  })

  it('allows member content after authentication', () => {
    expect(renderMember(true)).toContain('protected-content')
  })

  it('limits post-login redirects to known local member routes', () => {
    expect(safeReturnPath('/history/test-result')).toBe('/history/test-result')
    expect(safeReturnPath('//evil.example')).toBe('/')
    expect(safeReturnPath('https://evil.example')).toBe('/')
    expect(safeReturnPath('/login')).toBe('/')
  })
})
