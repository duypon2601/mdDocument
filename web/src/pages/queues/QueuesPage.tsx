import { Link } from 'react-router'
import { useQueues } from '../../api/hooks'
import type { PendingActivity, QueueInfo, QueuePart, RunningWorkflow } from '../../api/types'
import { EmptyState } from '../../components/EmptyState'
import { ErrorState } from '../../components/ErrorState'
import { Skeleton } from '../../components/Skeleton'
import { StatusPill } from '../../components/StatusPill'
import { errText } from '../../hooks/useDocActions'
import { formatTime, parseUtc } from '../../lib/format'
import {
  ACTIVITY_STATE_LABEL,
  formatDuration,
  missingWorkers,
  QUEUE_ROLE,
  since,
} from '../../lib/queues'
import { useDocumentTitle } from '../../lib/useDocumentTitle'

export function QueuesPage() {
  useDocumentTitle('Hàng đợi')
  const q = useQueues()
  // Mốc "bây giờ" lấy theo lúc server chụp, để thời gian không lệch giữa hai lần làm mới
  const now = q.data ? parseUtc(q.data.fetched_at).getTime() : 0

  return (
    <section>
      <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
        <h1 className="text-2xl font-semibold">Hàng đợi</h1>
        {q.data && (
          <p className="text-sm text-muted" aria-live="polite">
            Tự làm mới 2 giây một lần · lần cuối {formatTime(q.data.fetched_at)}
            {q.isError && <span className="ml-2 text-bad-fg">(lần làm mới gần nhất bị lỗi)</span>}
          </p>
        )}
      </div>

      {q.isError && !q.data ? (
        <ErrorState
          title="Không đọc được Temporal"
          detail={errText(q.error)}
          onRetry={() => q.refetch()}
        />
      ) : q.isPending ? (
        <Skeleton rows={4} />
      ) : (
        <>
          <ul className="grid gap-3 md:grid-cols-3">
            {q.data.queues.map((x) => (
              <QueueCard key={x.name} q={x} now={now} />
            ))}
          </ul>

          <h2 className="mt-8 mb-3 text-lg font-semibold">
            Workflow đang chạy ({q.data.running.length}
            {q.data.running_truncated ? '+' : ''})
          </h2>
          {q.data.running.length === 0 ? (
            <EmptyState title="Không có workflow nào đang chạy" />
          ) : (
            <ul className="space-y-3">
              {q.data.running.map((w) => (
                <RunningRow key={w.workflow_id} w={w} now={now} />
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  )
}

function QueueCard({ q, now }: { q: QueueInfo; now: number }) {
  const bad = missingWorkers(q)
  return (
    <li
      className={`rounded-lg border bg-surface p-4 ${bad ? 'border-bad-fg/60' : 'border-line'}`}
      aria-label={`Queue ${q.name}`}
    >
      <div className="flex items-center justify-between gap-2">
        <h2 className="font-mono font-semibold">{q.name}</h2>
        {bad ? (
          <span className="rounded-full bg-bad-bg px-2 py-0.5 text-xs font-medium text-bad-fg">
            Thiếu worker
          </span>
        ) : (
          <span className="rounded-full bg-ok-bg px-2 py-0.5 text-xs font-medium text-ok-fg">
            Sẵn sàng
          </span>
        )}
      </div>
      {QUEUE_ROLE[q.name] && <p className="mt-1 text-xs text-muted">{QUEUE_ROLE[q.name]}</p>}
      {q.expects_workflow && <Part label="Workflow task" p={q.workflow} now={now} />}
      <Part label="Activity task" p={q.activity} now={now} />
    </li>
  )
}

function Part({ label, p, now }: { label: string; p: QueuePart; now: number }) {
  return (
    <div className="mt-3 border-t border-line pt-3">
      <p className="text-sm font-medium">{label}</p>
      <dl className="mt-1 grid grid-cols-2 gap-x-3 gap-y-0.5 text-sm">
        <dt className="text-muted">Task chờ</dt>
        <dd className={p.backlog > 0 ? 'font-semibold text-warn-fg' : ''}>{p.backlog}</dd>
        {p.backlog > 0 && (
          <>
            <dt className="text-muted">Chờ lâu nhất</dt>
            <dd>{formatDuration(p.backlog_age_s)}</dd>
          </>
        )}
        <dt className="text-muted">Thêm / nhận</dt>
        <dd>
          {p.add_rate} / {p.dispatch_rate} mỗi giây
        </dd>
      </dl>
      <p className="mt-2 text-xs text-muted">Worker ({p.pollers.length})</p>
      {p.pollers.length === 0 ? (
        <p className="text-sm text-bad-fg">Không có worker nào đang nghe</p>
      ) : (
        <ul className="text-sm">
          {p.pollers.map((w) => (
            <li key={w.identity} className="flex justify-between gap-2">
              <span className="truncate font-mono" title={w.identity}>
                {w.identity}
              </span>
              <span className="shrink-0 text-xs text-muted">
                {w.last_access ? `${since(w.last_access, now)} trước` : ''}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function RunningRow({ w, now }: { w: RunningWorkflow; now: number }) {
  const name = w.file_name ?? w.workflow_id
  return (
    <li className="rounded-lg border border-line bg-surface p-4">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        {w.doc_id && w.file_name ? (
          <Link to={`/files/${w.doc_id}`} className="font-medium text-accent hover:underline">
            {name}
          </Link>
        ) : (
          <span className="font-medium">{name}</span>
        )}
        {w.status && <StatusPill status={w.status} />}
        <span className="text-xs text-muted">{w.workflow_type}</span>
        {w.started_at && (
          <span className="ml-auto text-xs text-muted">chạy được {since(w.started_at, now)}</span>
        )}
      </div>
      {w.activities.length === 0 ? (
        <p className="mt-2 text-sm text-muted">
          Không có activity nào đang chờ (workflow đang xử lý hoặc chờ duyệt)
        </p>
      ) : (
        <ul className="mt-2 space-y-1">
          {w.activities.map((a, i) => (
            <ActivityRow key={`${a.name}-${i}`} a={a} now={now} />
          ))}
        </ul>
      )}
    </li>
  )
}

function ActivityRow({ a, now }: { a: PendingActivity; now: number }) {
  const waiting = a.state === 'SCHEDULED'
  const pill = waiting ? 'bg-warn-bg text-warn-fg' : 'bg-run-bg text-run-fg'
  const from = waiting ? a.scheduled_at : a.started_at
  return (
    <li className="rounded-md bg-surface-2 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-mono">{a.name}</span>
        {a.task_queue && <span className="font-mono text-xs text-muted">{a.task_queue}</span>}
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${pill}`}>
          {ACTIVITY_STATE_LABEL[a.state]}
        </span>
        {from && <span className="text-xs text-muted">{since(from, now)}</span>}
        {a.attempt > 1 && (
          <span className="text-xs font-medium text-warn-fg">lần thử {a.attempt}</span>
        )}
        {a.worker && !waiting && (
          <span className="ml-auto font-mono text-xs text-muted">{a.worker}</span>
        )}
      </div>
      {a.last_failure && (
        <p className="mt-1 text-xs break-words text-bad-fg">Lỗi lần trước: {a.last_failure}</p>
      )}
    </li>
  )
}
