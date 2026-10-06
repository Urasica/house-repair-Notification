import type { Catalog, Context } from '../features/survey/storage'
import { facilityLabel } from '../features/survey/presentation'

export default function SelectionSummary({ catalog, context }: { catalog: Catalog; context: Context }) {
  const items = [
    ['주택', catalog.housingTypes.find(item => item.id === context.housingType)?.label],
    ['공간', catalog.rooms.find(item => item.id === context.roomId)?.label],
    ['시설물', facilityLabel(catalog, context.roomId, context.facilityId)],
    ['증상', catalog.symptoms.find(item => item.id === context.symptomId)?.label],
  ]
  return <aside className="selection-summary" aria-label="현재 선택 내용">
    <p className="eyebrow">현재 선택</p><h2>이 내용을 확인할게요</h2>
    <dl>{items.map(([label, value]) => <div key={label}><dt>{label}</dt><dd className={value ? '' : 'unselected'}>{value ?? '아직 선택하지 않았어요'}</dd></div>)}</dl>
    <p className="summary-help">잘 모르는 항목은 비워 두어도 괜찮아요. 확인이 필요한 내용을 함께 안내해 드려요.</p>
  </aside>
}
