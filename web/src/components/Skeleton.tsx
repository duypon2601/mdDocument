/** Khung chờ khi đang tải; đọc bằng screen reader là "Đang tải…". */
export function Skeleton({ rows = 3, label = 'Đang tải…' }: { rows?: number; label?: string }) {
  return (
    <div role="status" className="animate-pulse space-y-3 py-4 motion-reduce:animate-none">
      <span className="sr-only">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} aria-hidden="true" className="h-10 rounded-md bg-surface-2" />
      ))}
    </div>
  )
}
