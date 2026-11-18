import { expect, test } from '@playwright/test'

test('HTTPS deployment enforces secure cookies, origin, CSRF and body limits', async ({ page, baseURL }) => {
  test.skip(!baseURL?.startsWith('https://'), 'Requires an HTTPS deployment')
  const origin = new URL(baseURL!).origin
  const api = page.request
  const credentials = { email: `deploy-${Date.now()}@example.com`, password: 'test-only-strong-passphrase' }
  const headers = { Origin: origin }
  expect((await api.post('/api/v1/auth/register', { data: credentials, headers })).status()).toBe(201)
  const login = await api.post('/api/v1/auth/login', { data: credentials, headers })
  expect(login.status()).toBe(200)
  const auth = await login.json()
  const cookie = (await page.context().cookies()).find(item => item.name === '__Host-repair_auth')
  expect(cookie).toMatchObject({ secure: true, httpOnly: true, sameSite: 'Lax', path: '/' })
  const rejected = await api.post('/api/v1/auth/logout', {
    data: {}, headers: { Origin: 'https://untrusted.invalid', 'X-CSRF-Token': auth.csrfToken },
  })
  expect(rejected.status()).toBe(403)
  expect((await api.post('/api/v1/auth/logout', { data: {}, headers })).status()).toBe(403)
  const ready = await api.get('/health/ready')
  expect(ready.headers()['cache-control']).toBe('no-store')
  expect(ready.headers()['x-content-type-options']).toBe('nosniff')
  expect((await api.post('/api/v1/auth/register', {
    data: { ...credentials, password: 'x'.repeat(70000) }, headers,
  })).status()).toBe(413)
  expect((await api.post('/api/v1/auth/logout', {
    data: {}, headers: { ...headers, 'X-CSRF-Token': auth.csrfToken },
  })).status()).toBe(204)
  expect((await api.get('/api/v1/auth/me')).ok()).toBe(true)
  expect((await (await api.get('/api/v1/auth/me')).json()).user).toBeNull()
})
