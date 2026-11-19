import { useId, useRef, useState } from 'react'
import type { Guidance } from '../features/survey/storage'

export default function ContactDraft({ result }: { result: Guidance }) {
  const draftId = useId()
  const editor = useRef<HTMLTextAreaElement>(null)
  const [edited, setEdited] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [copyMessage, setCopyMessage] = useState('')
  const [copyFailed, setCopyFailed] = useState(false)
  const { summary } = result
  const description = summary.description.trim()
  const inquiry = edited ?? [
    `주택: ${summary.housingLabel}`,
    `위치: ${summary.roomLabel} · ${summary.facilityLabel}`,
    `증상: ${summary.symptomLabel}`,
    ...summary.answerLabels,
    result.contactDraft,
  ].join('\n')

  function change(value: string) {
    setEdited(value)
    setCopyMessage('')
    setCopyFailed(false)
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(inquiry)
      setCopyFailed(false)
      setCopyMessage('문의 내용을 복사했어요.')
    } catch {
      setCopyFailed(true)
      setCopyMessage('자동으로 복사하지 못했어요. 문의 문장을 직접 복사해 주세요.')
      editor.current?.focus()
      editor.current?.select()
    }
  }

  return <section aria-labelledby="contact-heading">
    <h2 id="contact-heading" tabIndex={-1}>직접 문의할 내용</h2>
    {editing ? <>
      <label htmlFor={draftId}>복사할 문의 문장</label>
      <textarea id={draftId} ref={editor} className="copy-text" rows={7} autoFocus value={inquiry} onChange={event => change(event.target.value)} />
      {description && !inquiry.includes(description) && <button type="button" className="secondary" onClick={() => {
        change(`${inquiry.trimEnd()}\n추가 설명: ${description}`)
        editor.current?.focus()
      }}>내가 적은 설명 넣기</button>}
    </> : <p className="contact-draft">{inquiry}</p>}
    <div className="actions">
      <button type="button" className="secondary" aria-expanded={editing} onClick={() => { setEditing(!editing); setCopyFailed(false) }}>{editing ? '문의 문장 확인' : '문의 문장 수정'}</button>
      <button type="button" className="secondary" disabled={!inquiry.trim()} onClick={() => void copy()}>문의 내용 복사</button>
    </div>
    <p role="status">{copyMessage}</p>
    {copyFailed && !editing && <textarea className="copy-text" aria-label="복사할 문의 내용" readOnly autoFocus rows={6} value={inquiry} onFocus={event => event.target.select()} />}
  </section>
}
