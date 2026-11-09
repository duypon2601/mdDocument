import { useState } from 'react'
import { ApiError } from '../api/client'
import { useCancel, useReindex, useReview } from '../api/hooks'
import { useToast } from '../components/Toast'

export function errText(e: unknown): string {
  return e instanceof ApiError ? e.detail : 'Không gọi được API'
}

interface Target {
  doc_id: string
  file_name: string
}

/** Dừng, Re-index, Duyệt/Từ chối kèm Toast báo kết quả; dùng chung cho bảng và trang chi tiết. */
export function useDocActions() {
  const toast = useToast()
  const cancel = useCancel()
  const reindex = useReindex()
  const review = useReview()
  const [busyId, setBusyId] = useState<string | null>(null)

  async function run(d: Target, job: () => Promise<unknown>, ok: string, fail: string) {
    setBusyId(d.doc_id)
    try {
      await job()
      toast.show(ok, 'success')
    } catch (e) {
      toast.show(`${fail}: ${errText(e)}`, 'error')
    } finally {
      setBusyId(null)
    }
  }

  return {
    busyId,
    stop: (d: Target) =>
      run(
        d,
        () => cancel.mutateAsync(d.doc_id),
        `Đã gửi yêu cầu dừng ${d.file_name}`,
        `Không dừng được ${d.file_name}`,
      ),
    reindex: (d: Target) =>
      run(
        d,
        () => reindex.mutateAsync(d.doc_id),
        `Đã yêu cầu re-index ${d.file_name}`,
        `Không re-index được ${d.file_name}`,
      ),
    review: (d: Target, decision: 'approve' | 'reject') =>
      run(
        d,
        () => review.mutateAsync({ id: d.doc_id, decision }),
        decision === 'approve' ? `Đã duyệt ${d.file_name}` : `Đã từ chối ${d.file_name}`,
        `Không gửi được quyết định cho ${d.file_name}`,
      ),
  }
}
