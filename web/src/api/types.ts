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
