import { afterEach, describe, expect, it, vi } from 'vitest'
import { catalogIsReady } from './catalog'

afterEach(() => vi.unstubAllGlobals())

describe('catalog readiness', () => {
  it('shows preparation for a missing completed catalog', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: { code: 'CATALOG_NOT_READY' } }), { status: 503 },
    )))
    expect(await catalogIsReady()).toBe(false)
  })

  it('keeps a database outage separate from catalog preparation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ error: { code: 'SERVICE_UNAVAILABLE' } }), { status: 503 },
    )))
    await expect(catalogIsReady()).rejects.toThrow('서비스에 연결하지 못했어요')
  })
})
