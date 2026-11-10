// Hợp đồng API: docs/giao-dien/ke-hoach.md, mục "API cần thêm".

export const STATUSES = [
  'RECEIVED',
  'CONVERTING',
  'NEEDS_REVIEW',
  'CONVERTED',
  'INDEXING',
  'INDEXED',
  'FAILED',
  'CANCELLED',
] as const
export type Status = (typeof STATUSES)[number]

export type Profile = 'legacy' | 'v1' | 'v2'

export interface Document {
  doc_id: string
  file_name: string
  mime: string
  size: number
  status: Status
  error_code: string | null
  chunk_count: number
  index_version: number
  embedding_model: string
  /** Có thể thiếu múi giờ, coi là UTC. */
  created_at: string
  updated_at: string
  extract_media: boolean
  profile: Profile
}

/** GET /documents/{id}: có thêm progress khi tài liệu đang chạy. */
export interface DocumentDetail extends Document {
  progress: string | null
}

export interface DocumentList {
  items: Document[]
  total: number
  limit: number
  offset: number
}

export interface ListParams {
  /** Một hoặc nhiều trạng thái, gửi dạng A,B. */
  status?: Status | Status[]
  q?: string
  limit?: number
  offset?: number
}

/** Kết quả upload: Document kèm cờ duplicate (200 = trùng, 202 = mới). */
export type UploadResult = Document & { duplicate: boolean }

export interface Stats {
  total: number
  chunks: number
  by_status: Record<Status, number>
}

export interface Chunk {
  chunk_index: number
  text: string
  heading_path: string[] | string
  page_start: number
  page_end: number
  content_hash: string
}

export interface ChunkPage {
  doc_id: string
  index_version: number
  total: number
  offset: number
  limit: number
  items: Chunk[]
}

export interface ChunkParams {
  version?: number
  offset?: number
  limit?: number
}

export interface SearchRequest {
  query: string
  top_k?: number
  doc_id?: string | null
}

export interface SearchHit {
  score: number
  doc_id: string
  file_name: string
  index_version: number
  chunk_index: number
  heading_path: string[] | string
  page_start: number
  page_end: number
  text: string
}

export interface SearchResponse {
  query: string
  model: string
  results: SearchHit[]
}

export interface CancelRunningResult {
  requested: string[]
  failed: { doc_id: string; detail: string }[]
}

export interface ReindexResult {
  doc_id: string
  index_version: number
}

export interface CancelResult {
  doc_id: string
  cancel_requested: boolean
}

/** GET /temporal/queues: đọc thẳng từ Temporal. */
export interface QueuePoller {
  identity: string
  last_access: string | null
}

export interface QueuePart {
  pollers: QueuePoller[]
  /** Số task đang chờ worker nhận (ước lượng của Temporal). */
  backlog: number
  backlog_age_s: number
  add_rate: number
  dispatch_rate: number
}

export interface QueueInfo {
  name: string
  /** Chỉ queue chạy workflow mới cần worker cho phần workflow. */
  expects_workflow: boolean
  workflow: QueuePart
  activity: QueuePart
}

export type ActivityState =
  | 'SCHEDULED'
  | 'STARTED'
  | 'CANCEL_REQUESTED'
  | 'PAUSED'
  | 'PAUSE_REQUESTED'
  | 'UNKNOWN'

export interface PendingActivity {
  name: string
  task_queue: string | null
  state: ActivityState
  attempt: number
  scheduled_at: string | null
  started_at: string | null
  worker: string | null
  last_failure: string | null
}

export interface RunningWorkflow {
  workflow_id: string
  workflow_type: string
  doc_id: string | null
  file_name: string | null
  status: Status | null
  started_at: string | null
  activities: PendingActivity[]
}

export interface QueueSnapshot {
  fetched_at: string
  queues: QueueInfo[]
  running: RunningWorkflow[]
  running_truncated: boolean
}
