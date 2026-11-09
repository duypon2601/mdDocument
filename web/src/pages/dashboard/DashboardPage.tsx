import { Link } from 'react-router'
import { useDocuments, useStats } from '../../api/hooks'
import type { Status } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Skeleton } from '../../components/Skeleton'
import { StatusPill } from '../../components/StatusPill'
import { runningCount, StopAllButton } from '../../components/StopAllButton'
import { errText } from '../../hooks/useDocActions'
import { formatTime } from '../../lib/format'
import { statusLabel } from '../../lib/status'
import { useDocumentTitle } from '../../lib/useDocumentTitle'

/** Thẻ theo trạng thái; key khớp tab ở /files (running gộp 5 trạng thái đang chạy). */
const CARDS: { status: Status; to: string }[] = [
  { status: 'NEEDS_REVIEW', to: 'NEEDS_REVIEW' },
  { status: 'INDEXED', to: 'INDEXED' },
  { status: 'FAILED', to: 'FAILED' },
  { status: 'CANCELLED', to: 'CANCELLED' },
]

const card = 'block rounded-lg border border-line bg-surface p-4 hover:bg-surface-2'

export function DashboardPage() {
  useDocumentTitle('Tổng quan')
  const stats = useStats()
  const latest = useDocuments({ limit: 5 })

  return (
    <section>
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold">Tổng quan</h1>
        <StopAllButton />
      </div>

      {stats.isError && !stats.data ? (
        <ErrorState detail={errText(stats.error)} onRetry={() => stats.refetch()} />
      ) : stats.isPending ? (
        <Skeleton rows={2} />
      ) : (
        <ul className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          <li className="col-span-2 lg:col-span-4">
            <Link
              to="/files?status=running"
              className="flex items-baseline justify-between rounded-lg border border-run-fg/40 bg-run-bg p-4 text-run-fg hover:opacity-90"
            >
              <span className="font-medium">Đang chạy</span>
              <span className="text-3xl font-semibold">{runningCount(stats.data.by_status)}</span>
            </Link>
          </li>
          {CARDS.map((c) => (
            <li key={c.status}>
              <Link to={`/files?status=${c.to}`} className={card}>
                <span className="block text-sm text-muted">{statusLabel(c.status)}</span>
                <span className="text-2xl font-semibold">{stats.data.by_status[c.status]}</span>
              </Link>
            </li>
          ))}
          <li className="col-span-2 lg:col-span-4">
            <div className="flex flex-wrap gap-x-8 gap-y-1 rounded-lg border border-line bg-surface p-4 text-sm">
              <span>
                <span className="text-muted">Tổng tài liệu </span>
                <strong>{stats.data.total}</strong>
              </span>
              <span>
                <span className="text-muted">Tổng chunk </span>
                <strong>{stats.data.chunks}</strong>
              </span>
            </div>
          </li>
        </ul>
      )}

      <h2 className="mt-8 mb-3 text-lg font-semibold">Tài liệu mới nhất</h2>
      {latest.isError && !latest.data ? (
        <ErrorState detail={errText(latest.error)} onRetry={() => latest.refetch()} />
      ) : latest.isPending ? (
        <Skeleton rows={3} />
      ) : latest.data.items.length === 0 ? (
        <EmptyState
          title="Chưa có tài liệu nào"
          action={
            <Link to="/files" className="text-accent underline">
              Tải file lên
            </Link>
          }
        />
      ) : (
        <ul className="divide-y divide-line rounded-lg border border-line bg-surface">
          {latest.data.items.map((d) => (
            <li key={d.doc_id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5">
              <Link to={`/files/${d.doc_id}`} className="font-medium break-all text-accent hover:underline">
                {d.file_name}
              </Link>
              <span className="flex items-center gap-3 text-sm text-muted">
                {formatTime(d.updated_at)}
                <StatusPill status={d.status} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
