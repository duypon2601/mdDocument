import type {
  CancelResult,
  CancelRunningResult,
  ChunkPage,
  ChunkParams,
  DocumentDetail,
  DocumentList,
  ListParams,
  QueueSnapshot,
  ReindexResult,
  SearchRequest,
  SearchResponse,
  Stats,
  UploadResult,
} from './types'

export class ApiError extends Error {
  status: number
  code: string | null
  detail: string

  constructor(status: number, code: string | null, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.detail = detail
  }
}

function detailText(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail
  if (detail == null) return fallback
  return JSON.stringify(detail)
}

async function toError(res: Response): Promise<ApiError> {
  const fallback = `${res.status} ${res.statusText}`.trim()
  try {
    const body = await res.json()
    return new ApiError(res.status, body?.code ?? null, detailText(body?.detail, fallback))
  } catch {
    return new ApiError(res.status, null, fallback)
  }
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch (e) {
    // fetch ném TypeError khi mất mạng hoặc API tắt
    throw new ApiError(0, 'NETWORK', e instanceof Error ? e.message : 'Không kết nối được API')
  }
  if (!res.ok) throw await toError(res)
  return res
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  return (await send(path, init)).json() as Promise<T>
}

function query(params: Record<string, string | number | undefined | null>): string {
  const sp = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v))
  }
  const s = sp.toString()
  return s ? `?${s}` : ''
}

const enc = encodeURIComponent

export const api = {
  listDocuments(p: ListParams = {}): Promise<DocumentList> {
    const status = Array.isArray(p.status) ? p.status.join(',') : p.status
    return json(`/documents${query({ status, q: p.q, limit: p.limit, offset: p.offset })}`)
  },

  getDocument(id: string): Promise<DocumentDetail> {
    return json(`/documents/${enc(id)}`)
  },

  async getMarkdown(id: string): Promise<string> {
    return (await send(`/documents/${enc(id)}/markdown`)).text()
  },

  getChunks(id: string, p: ChunkParams = {}): Promise<ChunkPage> {
    const qs = query({ version: p.version, offset: p.offset, limit: p.limit })
    return json(`/documents/${enc(id)}/chunks${qs}`)
  },

  rawUrl(id: string): string {
    return `/documents/${enc(id)}/raw`
  },

  getStats(): Promise<Stats> {
    return json('/stats')
  },

  getQueues(): Promise<QueueSnapshot> {
    return json('/temporal/queues')
  },

  upload(file: File): Promise<UploadResult> {
    const form = new FormData()
    form.append('file', file)
    return json('/documents', { method: 'POST', body: form })
  },

  review(id: string, decision: 'approve' | 'reject'): Promise<{ doc_id: string; decision: string }> {
    return json(`/documents/${enc(id)}/review${query({ decision })}`, { method: 'POST' })
  },

  reindex(id: string): Promise<ReindexResult> {
    return json(`/documents/${enc(id)}/reindex`, { method: 'POST' })
  },

  cancel(id: string): Promise<CancelResult> {
    return json(`/documents/${enc(id)}/cancel`, { method: 'POST' })
  },

  cancelRunning(): Promise<CancelRunningResult> {
    return json('/documents/cancel-running', { method: 'POST' })
  },

  search(body: SearchRequest): Promise<SearchResponse> {
    return json('/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  },
}
