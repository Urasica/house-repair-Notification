import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import type { Catalog } from './storage'
import { facilitiesForRoom, facilityLabel, roomFacilities, updateSelection } from './presentation'
import { catalog as fixture, filledSession } from './test-fixtures'

const reviewed = JSON.parse(readFileSync(new URL('../../../../data/catalog/m08a-20261004/catalog.json', import.meta.url), 'utf8')) as Omit<Catalog, 'publishedAt'>
const catalog: Catalog = { ...reviewed, publishedAt: '2026-10-04T00:00:00Z' }
const ids = (room: string) => facilitiesForRoom(catalog, room).map(item => item.id)

describe('room-specific navigation with the real published catalog', () => {
  it('shows entrance fixtures without kitchen, bathroom or heating equipment', () => {
    expect(ids('entrance')).toEqual(expect.arrayContaining(['door', 'intercom', 'tile', 'furniture', 'unknown']))
    for (const id of ['sink', 'sanitary', 'bath-finish', 'air', 'heating', 'appliance', 'gas', 'elevator']) expect(ids('entrance')).not.toContain(id)
    expect(ids('kitchen')).toContain('sink')
    expect(ids('kitchen')).not.toContain('bath-finish')
    expect(ids('bathroom')).toContain('bath-finish')
    expect(ids('bathroom')).not.toContain('sink')
    expect(facilityLabel(catalog, 'entrance', 'furniture')).toBe('신발장·수납 가구')
    expect(facilityLabel(catalog, 'kitchen', 'sanitary')).toBe('수전')
    expect(facilityLabel(catalog, 'bathroom', 'air')).toBe('욕실 환풍기')
    expect(facilityLabel(catalog, 'kitchen', 'sink')).toContain('마감')
    expect(facilityLabel(catalog, 'kitchen', 'pipe')).toContain('싱크대 아래')
  })
  it('keeps all navigation entries inside the catalog relationship and offers an unknown choice', () => {
    for (const [room, facilities] of Object.entries(roomFacilities)) {
      expect(catalog.rooms.some(item => item.id === room)).toBe(true)
      expect(new Set(facilities).size).toBe(facilities.length)
      for (const id of facilities) expect(catalog.facilities.find(item => item.id === id)?.roomIds).toContain(room)
      expect(ids(room)).toContain('unknown')
    }
    expect(ids('unknown')).toHaveLength(catalog.facilities.length)
    expect(facilitiesForRoom(catalog, null)).toEqual([])
  })
  it('does not reuse version-specific navigation for another catalog or alter published definitions', () => {
    expect(facilitiesForRoom(fixture, 'test-room').map(item => item.id)).toEqual(['test-facility'])
    expect(catalog.facilities.find(item => item.id === 'air')?.roomIds).toContain('entrance')
    expect(facilitiesForRoom({ ...catalog, version: 'future-catalog' }, 'entrance').some(item => item.id === 'air')).toBe(true)
  })
  it('resets downstream context even when both rooms allow the same facility', () => {
    const current = { ...filledSession().context, roomId: 'entrance', facilityId: 'door', symptomId: 'door-issue', answers: { detail: 'YES' } }
    expect(updateSelection(current, 'roomId', 'living')).toMatchObject({ roomId: 'living', facilityId: null, symptomId: null, answers: {} })
    expect(updateSelection(current, 'facilityId', 'tile')).toMatchObject({ facilityId: 'tile', symptomId: null, answers: {} })
    expect(updateSelection(current, 'roomId', 'entrance')).toBe(current)
  })
})
