import type { Guidance } from './storage'
export const statusLabels: Record<Guidance['status'], string> = { SAFETY_PRIORITY: '안전 확인 우선', OUT_OF_SCOPE: '지원 범위 확인', NEED_MORE_INFO: '추가 정보 필요', NEED_CONFIRMATION: '담당 기관 확인 필요', GUIDANCE_AVAILABLE: '관련 기준 안내' }
