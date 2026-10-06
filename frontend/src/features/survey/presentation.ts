import type { Catalog, Context } from './storage'

// Navigation categories for the reviewed M08A catalog, not legal applicability rules.
// Keep the published catalog and historical consultations immutable.
export const roomFacilities: Record<string, readonly string[]> = {
  entrance: ['door', 'tile', 'floor', 'furniture', 'intercom', 'light', 'finish', 'wallpaper', 'electric', 'unknown'],
  living: ['window', 'door', 'wallpaper', 'floor', 'finish', 'light', 'intercom', 'air', 'heating', 'furniture', 'electric', 'fire', 'concrete', 'unknown'],
  bedroom: ['door', 'window', 'wallpaper', 'floor', 'finish', 'furniture', 'light', 'heating', 'air', 'electric', 'fire', 'unknown'],
  kitchen: ['sink', 'furniture', 'sanitary', 'pipe', 'air', 'gas', 'appliance', 'tile', 'light', 'electric', 'finish', 'floor', 'unknown'],
  bathroom: ['sanitary', 'bath-finish', 'tile', 'waterproof', 'drain', 'pipe', 'door', 'air', 'light', 'finish', 'unknown'],
  laundry: ['sanitary', 'pipe', 'drain', 'waterproof', 'tile', 'window', 'door', 'electric', 'insulation', 'unknown'],
  balcony: ['window', 'railing', 'waterproof', 'drain', 'tile', 'pipe', 'sanitary', 'gas', 'door', 'finish', 'insulation', 'unknown'],
  common: ['door', 'window', 'railing', 'elevator', 'light', 'intercom', 'cctv', 'fire', 'tile', 'stone', 'finish', 'electric', 'unknown'],
  parking: ['parking-fixture', 'concrete', 'waterproof', 'drain', 'joint', 'light', 'cctv', 'fire', 'elevator', 'duct', 'pipe', 'penetration', 'unknown'],
  roof: ['waterproof', 'drain', 'joint', 'railing', 'concrete', 'penetration', 'duct', 'insulation', 'unknown'],
  outdoor: ['tree', 'pavement', 'retaining', 'railing', 'drain', 'light', 'cctv', 'gas', 'stone', 'electric', 'concrete', 'unknown'],
}

export function facilitiesForRoom(catalog: Catalog, roomId: string | null | undefined) {
  const allowed = catalog.facilities.filter(item => item.roomIds.includes(roomId ?? ''))
  const ordered = catalog.version === 'm08a-20261004-v2' ? roomFacilities[roomId ?? ''] : undefined
  return ordered ? ordered.flatMap(id => allowed.filter(item => item.id === id)) : allowed
}

export function facilityLabel(catalog: Catalog, roomId: string | null | undefined, facilityId: string | null | undefined) {
  const original = catalog.facilities.find(item => item.id === facilityId)?.label
  if (catalog.version !== 'm08a-20261004-v2') return original
  if (facilityId === 'furniture' && roomId === 'entrance') return '신발장·수납 가구'
  if (facilityId === 'furniture' && (roomId === 'living' || roomId === 'bedroom')) return '수납 가구'
  if (facilityId === 'door' && roomId === 'entrance') return '현관문·문틀'
  if (facilityId === 'sanitary' && ['kitchen', 'laundry', 'balcony'].includes(roomId ?? '')) return '수전'
  if (facilityId === 'air' && roomId === 'bathroom') return '욕실 환풍기'
  if (facilityId === 'air' && roomId === 'kitchen') return '주방 환기·후드'
  if (facilityId === 'air' && (roomId === 'living' || roomId === 'bedroom')) return '환기·에어컨'
  return original
}

export function updateSelection(context: Context, field: 'housingType' | 'roomId' | 'facilityId' | 'symptomId', value: string): Context {
  if ((context[field] ?? '') === value) return context
  const next = { ...context, [field]: value || null, answers: {} }
  if (field === 'roomId') { next.facilityId = null; next.symptomId = null }
  if (field === 'facilityId') next.symptomId = null
  return next as Context
}
