import type { ActivityState, QueueInfo } from '../api/types'
import { parseUtc } from './format'

/** Việc của từng queue, theo workflows/ingestion.py. */
export const QUEUE_ROLE: Record<string, string> = {
  'ingest-tq': 'Workflow và update_status',
  'convert-tq': 'detect_format, parse_document, ocr_pages, finalize_markdown',
  'index-tq': 'chunk_markdown, embed_and_upsert, cleanup_old_chunks',
}

export const ACTIVITY_STATE_LABEL: Record<ActivityState, string> = {
  SCHEDULED: 'Chờ worker',
  STARTED: 'Đang chạy',
  CANCEL_REQUESTED: 'Đang huỷ',
  PAUSED: 'Tạm dừng',
  PAUSE_REQUESTED: 'Đang tạm dừng',
  UNKNOWN: 'Không rõ',
}

/** Thiếu worker ở phần queue cần dùng. */
export function missingWorkers(q: QueueInfo): boolean {
  return q.activity.pollers.length === 0 || (q.expects_workflow && q.workflow.pollers.length === 0)
}

/** Tổng task đang chờ worker của queue (phần workflow chỉ tính khi có dùng). */
export function queueBacklog(q: QueueInfo): number {
  return q.activity.backlog + (q.expects_workflow ? q.workflow.backlog : 0)
}

/** Số worker riêng biệt đang poll queue (một process thường poll cả hai phần). */
export function workerCount(q: QueueInfo): number {
  return new Set([...q.workflow.pollers, ...q.activity.pollers].map((p) => p.identity)).size
}

/** Khoảng thời gian ngắn gọn: 5 giây, 3 phút, 2 giờ 10 phút. */
export function formatDuration(seconds: number): string {
  const s = Math.max(0, Math.round(seconds))
  if (s < 60) return `${s} giây`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} phút`
  const h = Math.floor(m / 60)
  return m % 60 ? `${h} giờ ${m % 60} phút` : `${h} giờ`
}

/** Bao lâu kể từ mốc thời gian (ISO), tính theo `now`. */
export function since(iso: string | null | undefined, now: number): string {
  if (!iso) return ''
  const t = parseUtc(iso).getTime()
  if (Number.isNaN(t)) return ''
  return formatDuration((now - t) / 1000)
}
