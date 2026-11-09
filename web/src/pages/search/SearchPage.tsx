import { useState, type FormEvent } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useDocuments, useSearch } from '../../api/hooks'
import type { SearchHit } from '../../api/types'
import { Button } from '../../components/Button'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { errText } from '../../hooks/useDocActions'
import { headingText, pageRange, splitHighlight } from '../../lib/highlight'

const TOP_K = [5, 8, 20] as const
const DEFAULT_K = 8

export function SearchPage() {
  const [sp, setSp] = useSearchParams()
  const query = (sp.get('q') ?? '').trim()
  const docId = sp.get('doc_id') ?? ''
  const kParam = Number(sp.get('k'))
  const topK = (TOP_K as readonly number[]).includes(kParam) ? kParam : DEFAULT_K
  const [text, setText] = useState(sp.get('q') ?? '')
  const docs = useDocuments({ status: 'INDEXED', limit: 200 })
  const search = useSearch(query ? { query, top_k: topK, doc_id: docId || null } : null)

  function update(patch: Record<string, string>) {
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(patch)) {
          if (v) next.set(k, v)
          else next.delete(k)
        }
        return next
      },
      { replace: true },
    )
  }

  function submit(e: FormEvent) {
    e.preventDefault()
    update({ q: text.trim() })
  }

  const items = docs.data?.items ?? []
  const known = items.some((d) => d.doc_id === docId)

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Tìm kiếm thử</h1>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3" role="search">
        <label className="flex min-w-60 flex-1 flex-col gap-1 text-sm">
          Câu hỏi
          <input
            type="search"
            value={text}
            onChange={(e) => setText(e.target.value)}
            maxLength={2000}
            placeholder="Nhập câu hỏi rồi nhấn Enter"
            className="min-h-9 rounded-md border border-line bg-surface px-3"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Số kết quả
          <select
            value={topK}
            onChange={(e) => update({ k: e.target.value === String(DEFAULT_K) ? '' : e.target.value })}
            className="min-h-9 rounded-md border border-line bg-surface px-2"
          >
            {TOP_K.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-48 max-w-full flex-col gap-1 text-sm">
          Tài liệu
          <select
            value={docId}
            onChange={(e) => update({ doc_id: e.target.value })}
            className="min-h-9 max-w-full rounded-md border border-line bg-surface px-2"
          >
            <option value="">Tất cả tài liệu</option>
            {docId && !known && <option value={docId}>{docId.slice(0, 12)}…</option>}
            {items.map((d) => (
              <option key={d.doc_id} value={d.doc_id}>
                {d.file_name}
              </option>
            ))}
          </select>
        </label>
        <Button type="submit" variant="primary" disabled={!text.trim()}>
          Tìm
        </Button>
      </form>

      <div className="mt-6" aria-live="polite">
        {!query ? (
          <EmptyState title="Nhập câu hỏi để bắt đầu">
            Kết quả là các chunk gần nghĩa nhất, xếp theo điểm.
          </EmptyState>
        ) : search.isPending ? (
          <p className="py-8 text-center text-muted">Đang tìm…</p>
        ) : search.isError ? (
          (search.error as { status?: number }).status === 503 ? (
            <ErrorState
              title="Chưa bật tìm kiếm: kiểm tra Qdrant và endpoint embedding"
              detail={errText(search.error)}
              onRetry={() => search.refetch()}
            />
          ) : (
            <ErrorState detail={errText(search.error)} onRetry={() => search.refetch()} />
          )
        ) : search.data.results.length === 0 ? (
          <EmptyState title="Không có kết quả">
            Không chunk nào khớp với “{query}”. Thử câu hỏi khác hoặc bỏ lọc tài liệu.
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {search.data.results.map((h) => (
              <Hit key={`${h.doc_id}-${h.index_version}-${h.chunk_index}`} hit={h} query={query} />
            ))}
          </ul>
        )}
      </div>
    </section>
  )
}

function Hit({ hit, query }: { hit: SearchHit; query: string }) {
  const heading = headingText(hit.heading_path)
  const pages = pageRange(hit.page_start, hit.page_end)
  return (
    <li className="rounded-lg border border-line bg-surface p-3">
      <div className="mb-2 flex flex-wrap items-baseline gap-x-3 gap-y-1 text-sm">
        <span className="font-mono font-medium" title="Điểm tương đồng">
          {hit.score.toFixed(2)}
        </span>
        <Link to={`/files/${hit.doc_id}`} className="font-medium text-accent break-all hover:underline">
          {hit.file_name}
        </Link>
        <span className="text-muted">#{hit.chunk_index}</span>
        {heading && <span className="text-muted break-words">{heading}</span>}
        {pages && <span className="text-muted">{pages}</span>}
      </div>
      <p className="text-sm break-words whitespace-pre-wrap">
        {splitHighlight(hit.text, query).map((s, i) =>
          s.hit ? (
            <mark key={i} className="rounded-sm bg-accent/25 px-0.5 text-inherit">
              {s.text}
            </mark>
          ) : (
            <span key={i}>{s.text}</span>
          ),
        )}
      </p>
    </li>
  )
}
