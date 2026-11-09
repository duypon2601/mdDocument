import type { Status } from '../api/types'
import { statusGroup, statusLabel, type StatusGroup } from '../lib/status'

const TONE: Record<StatusGroup, string> = {
  running: 'bg-run-bg text-run-fg',
  ok: 'bg-ok-bg text-ok-fg',
  bad: 'bg-bad-bg text-bad-fg',
}

export function StatusPill({ status }: { status: Status }) {
  const group = statusGroup(status)
  return (
    <span
      data-group={group}
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium whitespace-nowrap ${TONE[group]}`}
    >
      {statusLabel(status)}
    </span>
  )
}
