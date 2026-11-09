import { useState } from 'react'
import type { DocumentDetail } from '../../api/types'
import { Button } from '../../components/Button'
import { useToast } from '../../components/Toast'
import { formatSize, formatTime } from '../../lib/format'
import { PROFILES, profileOf } from '../../lib/profile'

export function InfoTab({ doc }: { doc: DocumentDetail }) {
  const toast = useToast()
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(doc.doc_id)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.show('Không copy được, hãy bôi đen và copy thủ công', 'error')
    }
  }

  const p = profileOf(doc)
  const rows: [string, React.ReactNode][] = [
    [
      'doc_id',
      <span className="flex flex-wrap items-center gap-2">
        <code className="break-all">{doc.doc_id}</code>
        <Button onClick={copy}>{copied ? 'Đã copy' : 'Copy'}</Button>
      </span>,
    ],
    ['Tên file', doc.file_name],
    ['Loại (mime)', doc.mime],
    ['Kích thước', formatSize(doc.size)],
    ['Profile', PROFILES.find((x) => x.value === p)?.label ?? p],
    ['index_version', doc.index_version],
    ['Mô hình embedding', doc.embedding_model || '—'],
    ['Số chunk', doc.chunk_count],
    ['Mã lỗi', doc.error_code ?? '—'],
    ['Tạo lúc', formatTime(doc.created_at)],
    ['Cập nhật lúc', formatTime(doc.updated_at)],
  ]
  return (
    <dl className="grid grid-cols-1 gap-x-6 gap-y-3 text-sm sm:grid-cols-[12rem_1fr]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted">{k}</dt>
          <dd className="break-words">{v}</dd>
        </div>
      ))}
    </dl>
  )
}
