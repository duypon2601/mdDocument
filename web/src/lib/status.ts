import type { Status } from '../api/types'

export const STATUS_LABEL: Record<Status, string> = {
  RECEIVED: 'Đã nhận',
  CONVERTING: 'Đang chuyển đổi',
  NEEDS_REVIEW: 'Chờ duyệt OCR',
  CONVERTED: 'Đã chuyển đổi',
  INDEXING: 'Đang index',
  INDEXED: 'Hoàn tất',
  FAILED: 'Lỗi',
  CANCELLED: 'Đã huỷ',
}

/** Trạng thái đang chạy: workflow còn sống, nút Dừng áp dụng được. */
export const RUNNING_STATUSES: readonly Status[] = [
  'RECEIVED',
  'CONVERTING',
  'NEEDS_REVIEW',
  'CONVERTED',
  'INDEXING',
]

export type StatusGroup = 'running' | 'ok' | 'bad'

export function statusGroup(status: Status): StatusGroup {
  if (status === 'INDEXED') return 'ok'
  if (status === 'FAILED' || status === 'CANCELLED') return 'bad'
  return 'running'
}

export function isRunning(status: Status): boolean {
  return RUNNING_STATUSES.includes(status)
}

export function statusLabel(status: string): string {
  return STATUS_LABEL[status as Status] ?? status
}
