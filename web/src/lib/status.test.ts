import { STATUSES } from '../api/types'
import { isRunning, RUNNING_STATUSES, statusGroup, statusLabel, STATUS_LABEL } from './status'

describe('status', () => {
  it('mọi trạng thái đều có nhãn tiếng Việt', () => {
    for (const s of STATUSES) expect(STATUS_LABEL[s]).toBeTruthy()
    expect(statusLabel('INDEXED')).toBe('Hoàn tất')
    expect(statusLabel('NEEDS_REVIEW')).toBe('Chờ duyệt OCR')
  })

  it('trạng thái lạ giữ nguyên chuỗi', () => {
    expect(statusLabel('XYZ')).toBe('XYZ')
  })

  it.each([
    ['RECEIVED', 'running'],
    ['CONVERTING', 'running'],
    ['NEEDS_REVIEW', 'running'],
    ['CONVERTED', 'running'],
    ['INDEXING', 'running'],
    ['INDEXED', 'ok'],
    ['FAILED', 'bad'],
    ['CANCELLED', 'bad'],
  ] as const)('%s thuộc nhóm %s', (s, group) => {
    expect(statusGroup(s)).toBe(group)
  })

  it('RUNNING_STATUSES khớp với backend (5 trạng thái)', () => {
    expect([...RUNNING_STATUSES].sort()).toEqual(
      ['CONVERTED', 'CONVERTING', 'INDEXING', 'NEEDS_REVIEW', 'RECEIVED'].sort(),
    )
    expect(isRunning('INDEXING')).toBe(true)
    expect(isRunning('INDEXED')).toBe(false)
  })
})
