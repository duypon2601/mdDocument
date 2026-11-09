import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from '@tanstack/react-query'
import { isRunning, RUNNING_STATUSES } from '../lib/status'
import { api } from './client'
import type {
  ChunkParams,
  DocumentDetail,
  DocumentList,
  ListParams,
  Profile,
  SearchRequest,
  Stats,
} from './types'

/** Có tài liệu đang chạy thì hỏi lại sau 2 giây, không thì 15 giây. */
export const POLL_RUNNING_MS = 2000
export const POLL_IDLE_MS = 15000

export const keys = {
  documents: ['documents'] as const,
  list: (p: ListParams) => ['documents', 'list', p] as const,
  document: (id: string) => ['documents', 'detail', id] as const,
  markdown: (id: string, stamp = '') => ['documents', 'markdown', id, stamp] as const,
  chunks: (id: string, p: ChunkParams) => ['documents', 'chunks', id, p] as const,
  stats: ['stats'] as const,
}

const pollList = (data: DocumentList | undefined) =>
  data?.items.some((d) => isRunning(d.status)) ? POLL_RUNNING_MS : POLL_IDLE_MS

const pollDoc = (data: DocumentDetail | undefined) =>
  data && isRunning(data.status) ? POLL_RUNNING_MS : POLL_IDLE_MS

const pollStats = (data: Stats | undefined) =>
  data && RUNNING_STATUSES.some((s) => data.by_status[s] > 0) ? POLL_RUNNING_MS : POLL_IDLE_MS

export function useDocuments(params: ListParams = {}) {
  return useQuery({
    queryKey: keys.list(params),
    queryFn: () => api.listDocuments(params),
    refetchInterval: (q) => pollList(q.state.data),
    placeholderData: keepPreviousData,
  })
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: keys.document(id ?? ''),
    queryFn: () => api.getDocument(id!),
    enabled: !!id,
    refetchInterval: (q) => pollDoc(q.state.data),
    retry: (count, err) => (err as { status?: number }).status !== 404 && count < 2,
  })
}

export function useStats() {
  return useQuery({
    queryKey: keys.stats,
    queryFn: api.getStats,
    refetchInterval: (q) => pollStats(q.state.data),
  })
}

/** `stamp` đổi khi tài liệu đổi trạng thái hoặc được cập nhật, để Markdown cũ (kể cả 404) không bị giữ lại. */
export function useMarkdown(id: string | undefined, enabled = true, stamp = '') {
  return useQuery({
    queryKey: keys.markdown(id ?? '', stamp),
    queryFn: () => api.getMarkdown(id!),
    enabled: !!id && enabled,
    retry: (count, err) => (err as { status?: number }).status !== 404 && count < 2,
  })
}

export function useChunks(id: string | undefined, params: ChunkParams = {}, enabled = true) {
  return useQuery({
    queryKey: keys.chunks(id ?? '', params),
    queryFn: () => api.getChunks(id!, params),
    enabled: !!id && enabled,
    placeholderData: keepPreviousData,
    retry: (count, err) => (err as { status?: number }).status !== 404 && count < 2,
  })
}

/** Tìm kiếm là POST nhưng không đổi dữ liệu, dùng query để kết quả gắn với tham số trên URL. */
export function useSearch(body: SearchRequest | null) {
  return useQuery({
    queryKey: ['search', body] as const,
    queryFn: () => api.search(body!),
    enabled: !!body,
    retry: false,
    staleTime: 30_000,
  })
}

function refresh(qc: QueryClient) {
  return Promise.all([
    qc.invalidateQueries({ queryKey: keys.documents }),
    qc.invalidateQueries({ queryKey: keys.stats }),
  ])
}

export function useUpload() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ file, profile }: { file: File; profile: Profile }) =>
      api.upload(file, profile),
    onSettled: () => refresh(qc),
  })
}

export function useReview() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: 'approve' | 'reject' }) =>
      api.review(id, decision),
    onSuccess: () => refresh(qc),
  })
}

export function useReindex() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => api.reindex(id), onSuccess: () => refresh(qc) })
}

export function useCancel() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: (id: string) => api.cancel(id), onSuccess: () => refresh(qc) })
}

export function useCancelRunning() {
  const qc = useQueryClient()
  return useMutation({ mutationFn: api.cancelRunning, onSuccess: () => refresh(qc) })
}
