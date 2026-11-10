import { Link } from 'react-router'
import { useQueues } from '../api/hooks'
import { missingWorkers, queueBacklog, workerCount } from '../lib/queues'

/** Tóm tắt queue trên header, hiện ở mọi trang. Bấm vào mở trang Hàng đợi. */
export function QueueStrip() {
  const q = useQueues()
  const base = 'flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md px-2 py-1 text-xs hover:bg-surface-2'

  if (!q.data) {
    return q.isError ? (
      <Link to="/queues" className={`${base} text-muted`}>
        Temporal: không kết nối được
      </Link>
    ) : null
  }

  return (
    <Link to="/queues" className={base} aria-label="Tình trạng hàng đợi, mở trang Hàng đợi">
      {q.data.queues.map((x) => {
        const bad = missingWorkers(x)
        const backlog = queueBacklog(x)
        return (
          <span key={x.name} className="flex items-center gap-1" title={x.name}>
            <span
              aria-hidden
              className={`inline-block size-2 rounded-full ${bad ? 'bg-bad-fg' : 'bg-ok-fg'}`}
            />
            <span className="font-mono">{x.name.replace(/-tq$/, '')}</span>
            <span className="text-muted">
              {workerCount(x)}w
              {backlog > 0 && <span className="font-semibold text-warn-fg"> · {backlog} chờ</span>}
            </span>
          </span>
        )
      })}
      <span className="text-muted">· {q.data.running.length} đang chạy</span>
    </Link>
  )
}
