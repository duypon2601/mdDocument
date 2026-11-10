import { formatDuration, since } from './queues'

it('formatDuration gọn theo đơn vị', () => {
  expect(formatDuration(4.6)).toBe('5 giây')
  expect(formatDuration(180)).toBe('3 phút')
  expect(formatDuration(7200)).toBe('2 giờ')
  expect(formatDuration(7800)).toBe('2 giờ 10 phút')
  expect(formatDuration(-3)).toBe('0 giây')
})

it('since tính từ mốc now, trống khi thiếu mốc', () => {
  const now = Date.parse('2026-11-10T03:00:00Z')
  expect(since('2026-11-10T02:59:30Z', now)).toBe('30 giây')
  expect(since(null, now)).toBe('')
})
