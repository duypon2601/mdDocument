import type { DocumentDetail } from '../../api/types'
import { statusLabel } from '../../lib/status'
import { buildTimeline, type StepState } from '../../lib/timeline'

const DOT: Record<StepState, string> = {
  done: 'bg-ok-fg border-ok-fg text-surface',
  current: 'bg-run-bg border-run-fg text-run-fg',
  failed: 'bg-bad-bg border-bad-fg text-bad-fg',
  todo: 'bg-surface border-line text-muted',
}

const MARK: Record<StepState, string> = { done: '✓', current: '●', failed: '✕', todo: '' }

const NOTE: Record<StepState, string> = {
  done: 'đã xong',
  current: 'đang ở bước này',
  failed: 'dừng ở bước này',
  todo: 'chưa tới',
}

export function Timeline({ doc }: { doc: DocumentDetail }) {
  const steps = buildTimeline(doc)
  return (
    <ol
      aria-label="Các bước xử lý"
      className="my-5 flex flex-col gap-3 md:flex-row md:items-start md:gap-0"
    >
      {steps.map((s, i) => (
        <li
          key={s.status}
          aria-current={s.state === 'current' || s.state === 'failed' ? 'step' : undefined}
          data-state={s.state}
          className="flex items-center gap-3 md:flex-1 md:flex-col md:text-center"
        >
          <span className="flex items-center md:w-full md:justify-center">
            <span
              aria-hidden="true"
              className={`hidden h-0.5 flex-1 md:block ${i === 0 ? 'invisible' : s.state === 'todo' ? 'bg-line' : 'bg-ok-fg'}`}
            />
            <span
              aria-hidden="true"
              className={`flex size-7 shrink-0 items-center justify-center rounded-full border-2 text-xs font-bold ${DOT[s.state]}`}
            >
              {MARK[s.state]}
            </span>
            <span
              aria-hidden="true"
              className={`hidden h-0.5 flex-1 md:block ${i === steps.length - 1 ? 'invisible' : s.state === 'done' ? 'bg-ok-fg' : 'bg-line'}`}
            />
          </span>
          <span className={`text-sm ${s.state === 'todo' ? 'text-muted' : 'font-medium'}`}>
            {statusLabel(s.status)}
            <span className="sr-only"> ({NOTE[s.state]})</span>
          </span>
        </li>
      ))}
    </ol>
  )
}
