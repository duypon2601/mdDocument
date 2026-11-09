/** Kích thước file dễ đọc, ví dụ 1.5 MB. */
export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let v = bytes / 1024
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v >= 10 ? v.toFixed(0) : v.toFixed(1)} ${units[i]}`
}

const HAS_ZONE = /(?:Z|[+-]\d{2}:?\d{2})$/i

/** Chuỗi thời gian không có múi giờ thì coi là UTC (giống hàm when() ở trang cũ). */
export function parseUtc(s: string): Date {
  return new Date(HAS_ZONE.test(s) ? s : `${s.replace(' ', 'T')}Z`)
}

export function formatTime(s: string | null | undefined): string {
  if (!s) return ''
  const d = parseUtc(s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('vi-VN')
}
