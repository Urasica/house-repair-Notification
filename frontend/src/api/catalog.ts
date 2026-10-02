import type { components } from './generated/schema'

export async function catalogIsReady(): Promise<boolean> {
  const response = await fetch('/api/v1/catalog', { cache: 'no-store' })
  if (response.ok) return true
  if (response.status === 503) {
    const payload = await response.json() as Partial<components['schemas']['ErrorResponse']>
    if (payload.error?.code === 'CATALOG_NOT_READY') return false
  }
  throw new Error('서비스에 연결하지 못했어요. 잠시 후 다시 시도해 주세요.')
}
