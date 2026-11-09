import { useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router'
import { api } from '../../api/client'
import { useDocument } from '../../api/hooks'
import type { DocumentDetail } from '../../api/types'
import { Button } from '../../components/Button'
import { ConfirmDialog } from '../../components/ConfirmDialog'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Skeleton } from '../../components/Skeleton'
import { StatusPill } from '../../components/StatusPill'
import { useToast } from '../../components/Toast'
import { errText, useDocActions } from '../../hooks/useDocActions'
import { useDocumentTitle } from '../../lib/useDocumentTitle'
import { PROFILE_LABEL, profileOf } from '../../lib/profile'
import { isRunning } from '../../lib/status'
import { ChunksTab } from './ChunksTab'
import { InfoTab } from './InfoTab'
import { MarkdownTab } from './MarkdownTab'
import { Timeline } from './Timeline'

const TABS = [
  { key: 'markdown', label: 'Markdown' },
  { key: 'chunks', label: 'Chunk' },
  { key: 'info', label: 'Thông tin' },
] as const
type TabKey = (typeof TABS)[number]['key']

export function DocumentPage() {
  const { docId } = useParams()
  const doc = useDocument(docId)
  useDocumentTitle(doc.data?.file_name ?? 'Tài liệu')

  if (doc.isPending) return <Skeleton rows={4} />
  if (doc.isError) {
    if ((doc.error as { status?: number }).status === 404) {
      return (
        <EmptyState
          title="Không tìm thấy tài liệu"
          action={
            <Link to="/files" className="text-accent hover:underline">
              Về danh sách tài liệu
            </Link>
          }
        >
          Tài liệu {docId} không tồn tại hoặc đã bị xoá.
        </EmptyState>
      )
    }
    return <ErrorState detail={errText(doc.error)} onRetry={() => doc.refetch()} />
  }
  return <Detail doc={doc.data} />
}

function Detail({ doc }: { doc: DocumentDetail }) {
  const toast = useToast()
  const actions = useDocActions()
  const [sp, setSp] = useSearchParams()
  const tab: TabKey = TABS.find((t) => t.key === sp.get('tab'))?.key ?? 'markdown'
  const [confirm, setConfirm] = useState<'stop' | 'reject' | null>(null)
  const busy = actions.busyId === doc.doc_id
  const p = profileOf(doc)

  async function downloadMarkdown() {
    try {
      const text = await api.getMarkdown(doc.doc_id)
      const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
      const a = document.createElement('a')
      a.href = url
      a.download = `${doc.file_name.replace(/\.[^.]+$/, '')}.md`
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      toast.show(`Không tải được Markdown: ${errText(e)}`, 'error')
    }
  }

  function onConfirm() {
    const what = confirm
    setConfirm(null)
    if (what === 'stop') void actions.stop(doc)
    if (what === 'reject') void actions.review(doc, 'reject')
  }

  return (
    <section>
      <p className="mb-2 text-sm">
        <Link to="/files" className="text-accent hover:underline">
          ← Tài liệu
        </Link>
      </p>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <h1 className="text-2xl font-semibold break-all">{doc.file_name}</h1>
        <span className="rounded bg-surface-2 px-1.5 py-0.5 text-xs text-muted">
          {PROFILE_LABEL[p]}
        </span>
        <StatusPill status={doc.status} />
      </div>

      <div className="mt-4 flex flex-wrap gap-2">
        {doc.status === 'NEEDS_REVIEW' && (
          <>
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => void actions.review(doc, 'approve')}
            >
              Duyệt
            </Button>
            <Button variant="danger" disabled={busy} onClick={() => setConfirm('reject')}>
              Từ chối
            </Button>
          </>
        )}
        {isRunning(doc.status) && (
          <Button variant="danger" disabled={busy} onClick={() => setConfirm('stop')}>
            Dừng
          </Button>
        )}
        {doc.status === 'INDEXED' && (
          <>
            <Button disabled={busy} onClick={() => void actions.reindex(doc)}>
              Re-index
            </Button>
            <Button onClick={downloadMarkdown}>Tải Markdown</Button>
            <Link
              to={`/search?doc_id=${doc.doc_id}`}
              className="inline-flex min-h-9 items-center rounded-md border border-line bg-surface px-3.5 text-sm font-medium hover:bg-surface-2"
            >
              Tìm trong tài liệu này
            </Link>
          </>
        )}
        <a
          href={api.rawUrl(doc.doc_id)}
          download
          className="inline-flex min-h-9 items-center rounded-md border border-line bg-surface px-3.5 text-sm font-medium hover:bg-surface-2"
        >
          Tải file gốc
        </a>
      </div>

      <Timeline doc={doc} />

      <div role="tablist" aria-label="Nội dung tài liệu" className="mb-4 flex gap-1 border-b border-line">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            id={`tab-${t.key}`}
            aria-selected={t.key === tab}
            aria-controls="tab-panel"
            onClick={() =>
              setSp(
                (prev) => {
                  const next = new URLSearchParams(prev)
                  if (t.key === 'markdown') next.delete('tab')
                  else next.set('tab', t.key)
                  return next
                },
                { replace: true },
              )
            }
            className={`min-h-9 border-b-2 px-4 text-sm ${t.key === tab ? 'border-accent font-medium' : 'border-transparent text-muted hover:text-fg'}`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel" id="tab-panel" aria-labelledby={`tab-${tab}`}>
        {tab === 'markdown' && <MarkdownTab doc={doc} />}
        {tab === 'chunks' && <ChunksTab doc={doc} />}
        {tab === 'info' && <InfoTab doc={doc} />}
      </div>

      <ConfirmDialog
        open={confirm !== null}
        title={confirm === 'reject' ? 'Từ chối tài liệu?' : 'Dừng xử lý tài liệu?'}
        confirmLabel={confirm === 'reject' ? 'Từ chối' : 'Dừng'}
        onConfirm={onConfirm}
        onCancel={() => setConfirm(null)}
      >
        {confirm === 'reject'
          ? `${doc.file_name} sẽ bị từ chối và không được index.`
          : `${doc.file_name} sẽ chuyển sang trạng thái Đã huỷ.`}
      </ConfirmDialog>
    </section>
  )
}
