import { formatSize, formatTime, parseUtc } from './format'

describe('formatSize', () => {
  it.each([
    [0, '0 B'],
    [1023, '1023 B'],
    [1536, '1.5 KB'],
    [10 * 1024, '10 KB'],
    [5 * 1024 * 1024, '5.0 MB'],
    [3 * 1024 ** 3, '3.0 GB'],
  ])('%i byte', (n, expected) => {
    expect(formatSize(n)).toBe(expected)
  })
})

describe('parseUtc', () => {
  it('chuỗi không có múi giờ được coi là UTC', () => {
    expect(parseUtc('2026-11-09T05:00:00').toISOString()).toBe('2026-11-09T05:00:00.000Z')
    expect(parseUtc('2026-11-09 05:00:00').toISOString()).toBe('2026-11-09T05:00:00.000Z')
  })

  it('giữ nguyên chuỗi đã có múi giờ', () => {
    expect(parseUtc('2026-11-09T05:00:00Z').toISOString()).toBe('2026-11-09T05:00:00.000Z')
    expect(parseUtc('2026-11-09T12:00:00+07:00').toISOString()).toBe('2026-11-09T05:00:00.000Z')
  })
})

describe('formatTime', () => {
  it('rỗng thì trả chuỗi rỗng', () => {
    expect(formatTime(null)).toBe('')
    expect(formatTime(undefined)).toBe('')
  })

  it('chuỗi không phân tích được thì trả lại nguyên văn', () => {
    expect(formatTime('không phải ngày')).toBe('không phải ngày')
  })
})
