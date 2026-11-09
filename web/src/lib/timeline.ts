import type { Status } from '../api/types'

export type StepState = 'done' | 'current' | 'todo' | 'failed'

export interface Step {
  status: Status
  state: StepState
}

const BASE: Status[] = ['RECEIVED', 'CONVERTING', 'CONVERTED', 'INDEXING', 'INDEXED']
const WITH_REVIEW: Status[] = [
  'RECEIVED',
  'CONVERTING',
  'NEEDS_REVIEW',
  'CONVERTED',
  'INDEXING',
  'INDEXED',
]

/**
 * Các bước của timeline. Bước hiện tại lấy từ progress nếu có, không thì từ status.
 * NEEDS_REVIEW chỉ hiện khi tài liệu đang ở bước đó: API không lưu lại việc đã qua duyệt.
 * FAILED và CANCELLED không nói rõ dừng ở đâu, đoán theo chunk_count: đã có chunk thì dừng
 * ở INDEXING, chưa có thì dừng ở CONVERTING.
 */
export function buildTimeline(doc: {
  status: Status
  progress?: string | null
  chunk_count: number
}): Step[] {
  const { status } = doc
  const ended = status === 'FAILED' || status === 'CANCELLED'
  let current: Status
  if (ended) current = doc.chunk_count > 0 ? 'INDEXING' : 'CONVERTING'
  else if (status === 'INDEXED') current = 'INDEXED'
  else current = WITH_REVIEW.includes(doc.progress as Status) ? (doc.progress as Status) : status

  const order = current === 'NEEDS_REVIEW' ? WITH_REVIEW : BASE
  const at = order.indexOf(current)
  return order.map((s, i) => {
    let state: StepState = i < at ? 'done' : i > at ? 'todo' : 'current'
    if (s === current && status === 'INDEXED') state = 'done'
    if (s === current && ended) state = 'failed'
    return { status: s, state }
  })
}
