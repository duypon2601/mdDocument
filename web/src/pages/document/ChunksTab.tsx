import { useState } from 'react'
import { useChunks } from '../../api/hooks'
import type { Chunk, DocumentDetail } from '../../api/types'
import { Button } from '../../components/Button'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { errText } from '../../hooks/useDocActions'
import { headingText, pageRange } from '../../lib/highlight'

export const CHUNK_PAGE_SIZE = 50

export function ChunksTab({ doc }: { doc: DocumentDetail }) {
  const current = doc.index_version
  const [picked, setPicked] = useState<number | null>(null)
  const [offset, setOffset] = useState(0)
  const version = picked ?? current
  const hasChunks = current >= 1
  const q = useChunks(doc.doc_id, { version, offset, limit: CHUNK_PAGE_SIZE }, hasChunks)

  if (!hasChunks) {
    return (
      <EmptyState title="Chưa có chunk">
        Tài liệu chưa được index lần nào nên chưa có chunk để xem.
      </EmptyState>
    )
  }

  const select = (
    <label className="flex items-center gap-2 text-sm">
      Version
      <select
        value={version}
        onChange={(e) => {
          setPicked(Number(e.target.value))
          setOffset(0)
        }}
        className="min-h-9 rounded-md border border-line bg-surface px-2"
      >
        {Array.from({ length: current }, (_, i) => current - i).map((v) => (
          <option key={v} value={v}>
            {v === current ? `${v} (hiện tại)` : v}
          </option>
        ))}
      </select>
    </label>
  )
  const header = current > 1 ? <div className="mb-3">{select}</div> : null

  if (q.isPending) return <p className="py-8 text-center text-muted">Đang tải…</p>
  if (q.isError) {
    if ((q.error as { status?: number }).status === 404) {
      return (
        <>
          {header}
          <EmptyState title={version === current ? 'Chưa có chunk' : 'Đã dọn sau re-index'}>
            {version === current
              ? 'Chunk của version hiện tại chưa sẵn sàng, thử lại sau khi index xong.'
              : `Chunk của version ${version} đã bị dọn sau lần re-index.`}
          </EmptyState>
        </>
      )
    }
    return <ErrorState detail={errText(q.error)} onRetry={() => q.refetch()} />
  }

  const { items, total } = q.data
  const from = total === 0 ? 0 : offset + 1
  const to = Math.min(offset + CHUNK_PAGE_SIZE, total)
  return (
    <div>
      {header}
      {items.length === 0 ? (
        <EmptyState title="Không có chunk nào" />
      ) : (
        <ul className="space-y-3">
          {items.map((c) => (
            <ChunkCard key={c.chunk_index} chunk={c} />
          ))}
        </ul>
      )}
      <div className="mt-4 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted">
          {from}–{to} / {total} chunk
        </span>
        <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - CHUNK_PAGE_SIZE))}>
          Trước
        </Button>
        <Button
          disabled={offset + CHUNK_PAGE_SIZE >= total}
          onClick={() => setOffset(offset + CHUNK_PAGE_SIZE)}
        >
          Sau
        </Button>
      </div>
    </div>
  )
}

function ChunkCard({ chunk }: { chunk: Chunk }) {
  const [open, setOpen] = useState(false)
  const heading = headingText(chunk.heading_path)
  const pages = pageRange(chunk.page_start, chunk.page_end)
  const long = chunk.text.split('\n').length > 6 || chunk.text.length > 600
  return (
    <li className="rounded-lg border border-line bg-surface p-3">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <span className="font-mono font-medium">#{chunk.chunk_index}</span>
        {heading && <span className="text-muted break-words">{heading}</span>}
        {pages && <span className="text-muted">{pages}</span>}
      </div>
      <p className={`text-sm break-words whitespace-pre-wrap ${open ? '' : 'line-clamp-6'}`}>
        {chunk.text}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setOpen(!open)}
          aria-expanded={open}
          className="mt-2 text-sm text-accent hover:underline"
        >
          {open ? 'Thu gọn' : 'Xem hết'}
        </button>
      )}
    </li>
  )
}
