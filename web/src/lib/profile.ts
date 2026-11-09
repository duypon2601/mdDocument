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

export function profileOf(d: Pick<Document, 'profile' | 'extract_media'>): Profile {
  return d.profile ?? (d.extract_media === false ? 'legacy' : 'v2')
}
