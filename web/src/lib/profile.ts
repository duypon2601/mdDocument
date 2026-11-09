import type { Document, Profile } from '../api/types'

export const PROFILES: { value: Profile; label: string; hint: string }[] = [
  { value: 'v2', label: 'Mới v2', hint: 'Sau chỉnh sửa: bắt sai dấu, gọi lại khi lỗi' },
  { value: 'v1', label: 'Mới v1', hint: 'Trước chỉnh sửa' },
  { value: 'legacy', label: 'Bản cũ', hint: 'Không bóc ảnh, chart' },
]

export const PROFILE_LABEL: Record<Profile, string> = {
  v2: 'mới v2',
  v1: 'mới v1',
  legacy: 'bản cũ',
}

const KEY = 'profile'

export function isProfile(v: unknown): v is Profile {
  return v === 'v2' || v === 'v1' || v === 'legacy'
}

/** Profile nhớ lần trước; localStorage có thể bị chặn nên bọc try/catch. */
export function loadProfile(): Profile {
  try {
    const v = localStorage.getItem(KEY)
    return isProfile(v) ? v : 'v2'
  } catch {
    return 'v2'
  }
}

export function saveProfile(p: Profile): void {
  try {
    localStorage.setItem(KEY, p)
  } catch {
    // bỏ qua: chỉ là tiện ích nhớ lựa chọn
  }
}

export function profileOf(d: Pick<Document, 'profile' | 'extract_media'>): Profile {
  return d.profile ?? (d.extract_media === false ? 'legacy' : 'v2')
}
