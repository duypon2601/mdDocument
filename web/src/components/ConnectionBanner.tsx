import { useStats } from '../api/hooks'

/** Hiện khi không gọi được API (fetch lỗi mạng); tự biến mất khi /stats trả lời lại. */
export function ConnectionBanner() {
  const stats = useStats()
  const lost = [stats.error, stats.failureReason].some(
    (e) => (e as { code?: string } | null)?.code === 'NETWORK',
  )
  if (!lost) return null
  return (
    <div role="alert" className="border-b border-bad-fg/40 bg-bad-bg px-4 py-2 text-center text-sm text-bad-fg">
      Mất kết nối API. Đang thử lại, trang sẽ tự cập nhật khi có lại.
    </div>
  )
}
