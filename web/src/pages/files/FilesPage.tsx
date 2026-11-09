import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router'
import { ApiError } from '../../api/client'
import { useCancel, useDocuments, useReindex } from '../../api/hooks'
import type { Document, ListParams, Status } from '../../api/types'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { useToast } from '../../components/Toast'
import { RUNNING_STATUSES } from '../../lib/status'
import { DocumentTable } from './DocumentTable'
import { UploadPanel } from './UploadPanel'

export const PAGE_SIZE = 20
export const SEARCH_DEBOUNCE_MS = 300

const TABS: { key: string; label: string; status?: Status[] }[] = [
  { key: '', label: 'Tất cả' },
  { key: 'running', label: 'Đang chạy', status: [...RUNNING_STATUSES] },
  { key: 'NEEDS_REVIEW', label: 'Chờ duyệt', status: ['NEEDS_REVIEW'] },
  { key: 'INDEXED', label: 'Hoàn tất', status: ['INDEXED'] },
  { key: 'FAILED', label: 'Lỗi', status: ['FAILED'] },
  { key: 'CANCELLED', label: 'Đã huỷ', status: ['CANCELLED'] },
]

function errText(e: unknown): string {
  return e instanceof ApiError ? e.detail : 'Không gọi được API'
}

export function FilesPage() {
  const [sp, setSp] = useSearchParams()
  const toast = useToast()
  const tab = TABS.find((t) => t.key === (sp.get('status') ?? '')) ?? TABS[0]
  const q = sp.get('q') ?? ''
  const page = Math.max(1, Number.parseInt(sp.get('page') ?? '1', 10) || 1)

  // Ô tìm giữ giá trị gõ dở; ghi lên URL sau 300ms
  const [text, setText] = useState(q)
  const [seenQ, setSeenQ] = useState(q)
  if (seenQ !== q) {
    // URL đổi từ ngoài (nút Back, link) thì ô tìm theo URL
    setSeenQ(q)
    setText(q)
  }
  useEffect(() => {
    if (text === q) return
    const t = setTimeout(() => update({ q: text, page: '' }), SEARCH_DEBOUNCE_MS)
    return () => clearTimeout(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [text])

  function update(changes: Record<string, string>) {
    setSp(
      (prev) => {
        const next = new URLSearchParams(prev)
        for (const [k, v] of Object.entries(changes)) {
          if (v && !(k === 'page' && v === '1')) next.set(k, v)
          else next.delete(k)
        }
        return next
      },
      { replace: true },
    )
  }

  const params: ListParams = {
    status: tab.status,
    q: q || undefined,
    limit: PAGE_SIZE,
    offset: (page - 1) * PAGE_SIZE,
  }
  const list = useDocuments(params)
  const cancel = useCancel()
  const reindex = useReindex()
  const [stopping, setStopping] = useState<Document | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  async function confirmStop() {
    const d = stopping
    if (!d) return
    setStopping(null)
    setBusyId(d.doc_id)
    try {
      await cancel.mutateAsync(d.doc_id)
      toast.show(`Đã gửi yêu cầu dừng ${d.file_name}`, 'success')
    } catch (e) {
      toast.show(`Không dừng được ${d.file_name}: ${errText(e)}`, 'error')
    } finally {
      setBusyId(null)
    }
  }

  async function doReindex(d: Document) {
    setBusyId(d.doc_id)
    try {
      await reindex.mutateAsync(d.doc_id)
      toast.show(`Đã yêu cầu re-index ${d.file_name}`, 'success')
    } catch (e) {
      toast.show(`Không re-index được ${d.file_name}: ${errText(e)}`, 'error')
    } finally {
      setBusyId(null)
    }
  }

  const total = list.data?.total ?? 0
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const filtered = !!tab.status || !!q

  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">Tài liệu</h1>
      <UploadPanel />

      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div role="tablist" aria-label="Lọc theo trạng thái" className="flex flex-wrap gap-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              type="button"
              role="tab"
              aria-selected={t.key === tab.key}
              onClick={() => update({ status: t.key, page: '' })}
              className={`min-h-9 rounded-md px-3 text-sm ${t.key === tab.key ? 'bg-accent text-accent-fg' : 'border border-line bg-surface hover:bg-surface-2'}`}
            >
              {t.label}
            </button>
          ))}
        </div>
        <input
          type="search"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Tìm theo tên file"
          aria-label="Tìm theo tên file"
          className="min-h-9 w-full rounded-md border border-line bg-surface px-3 text-sm sm:w-64"
        />
      </div>

      {list.isError && !list.data ? (
        <ErrorState detail={errText(list.error)} onRetry={() => list.refetch()} />
      ) : list.isPending ? (
        <p className="py-8 text-center text-muted">Đang tải…</p>
      ) : list.data.items.length === 0 ? (
        <EmptyState title={filtered ? 'Không có tài liệu phù hợp' : 'Chưa có tài liệu nào'}>
          {filtered ? 'Thử đổi bộ lọc hoặc từ khoá.' : 'Tải file lên ở khung phía trên.'}
        </EmptyState>
      ) : (
        <>
          <DocumentTable
            items={list.data.items}
            busyId={busyId}
            onStop={setStopping}
            onReindex={doReindex}
          />
          <nav
            aria-label="Phân trang"
            className="mt-3 flex flex-wrap items-center justify-between gap-2 text-sm"
          >
            <span className="text-muted">
              {total} tài liệu · Trang {page}/{pages}
            </span>
            <span className="flex gap-2">
              <Button disabled={page <= 1} onClick={() => update({ page: String(page - 1) })}>
                Trang trước
              </Button>
              <Button disabled={page >= pages} onClick={() => update({ page: String(page + 1) })}>
                Trang sau
              </Button>
            </span>
          </nav>
        </>
      )}

      <ConfirmDialog
        open={!!stopping}
        title="Dừng xử lý tài liệu?"
        confirmLabel="Dừng"
        onConfirm={confirmStop}
        onCancel={() => setStopping(null)}
      >
        {stopping?.file_name} sẽ chuyển sang trạng thái Đã huỷ.
      </ConfirmDialog>
    </section>
  )
}
