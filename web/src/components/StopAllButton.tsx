import { useState } from 'react'
import { useCancelRunning, useStats } from '../api/hooks'
import { errText } from '../hooks/useDocActions'
import { RUNNING_STATUSES } from '../lib/status'
import { Button } from './Button'
import { ConfirmDialog } from './ConfirmDialog'
import { useToast } from './Toast'

export function runningCount(by_status: Record<string, number> | undefined): number {
  return RUNNING_STATUSES.reduce((n, s) => n + (by_status?.[s] ?? 0), 0)
}

/** Nút "Dừng tất cả đang chạy": chỉ hiện khi có tài liệu chạy, hỏi xác nhận ghi rõ số lượng. */
export function StopAllButton() {
  const stats = useStats()
  const cancelAll = useCancelRunning()
  const toast = useToast()
  const [open, setOpen] = useState(false)
  const count = runningCount(stats.data?.by_status)

  async function confirm() {
    setOpen(false)
    try {
      const r = await cancelAll.mutateAsync()
      toast.show(`Đã gửi lệnh dừng ${r.requested.length} tài liệu`, 'success')
      if (r.failed.length > 0) {
        toast.show(
          `${r.failed.length} tài liệu không dừng được: ${r.failed.map((f) => `${f.doc_id.slice(0, 8)} (${f.detail})`).join('; ')}`,
          'error',
        )
      }
    } catch (e) {
      toast.show(`Không dừng được: ${errText(e)}`, 'error')
    }
  }

  if (count === 0 && !open) return null
  return (
    <>
      <Button variant="danger" disabled={cancelAll.isPending} onClick={() => setOpen(true)}>
        Dừng tất cả đang chạy
      </Button>
      <ConfirmDialog
        open={open}
        title="Dừng tất cả tài liệu đang chạy?"
        confirmLabel={`Dừng ${count} tài liệu`}
        onConfirm={confirm}
        onCancel={() => setOpen(false)}
      >
        {count} tài liệu đang chạy sẽ chuyển sang trạng thái Đã huỷ.
      </ConfirmDialog>
    </>
  )
}
