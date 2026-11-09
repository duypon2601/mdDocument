import type { Status } from '../api/types'
import { stripFrontMatter } from './markdown'
import { buildTimeline } from './timeline'

const states = (status: Status, progress: string | null = null, chunk_count = 0) =>
  buildTimeline({ status, progress, chunk_count }).map((s) => `${s.status}:${s.state}`)

describe('buildTimeline', () => {
  it('bước hiện tại lấy từ status', () => {
    expect(states('CONVERTED')).toEqual([
      'RECEIVED:done',
      'CONVERTING:done',
      'CONVERTED:current',
      'INDEXING:todo',
      'INDEXED:todo',
    ])
  })

  it('progress ưu tiên hơn status', () => {
    expect(states('RECEIVED', 'INDEXING')[3]).toBe('INDEXING:current')
  })

  it('NEEDS_REVIEW chỉ hiện khi đang ở bước đó', () => {
    const s = states('NEEDS_REVIEW')
    expect(s).toContain('NEEDS_REVIEW:current')
    expect(s).toHaveLength(6)
    expect(states('CONVERTING')).toHaveLength(5)
  })

  it('INDEXED xong cả chuỗi', () => {
    expect(states('INDEXED').every((x) => x.endsWith(':done'))).toBe(true)
  })

  it('FAILED tô đỏ bước dở theo chunk_count', () => {
    expect(states('FAILED')).toContain('CONVERTING:failed')
    expect(states('CANCELLED', null, 5)).toContain('INDEXING:failed')
  })
})

describe('stripFrontMatter', () => {
  it('bỏ front-matter', () => {
    expect(stripFrontMatter('---\ntitle: a\n---\n\n# Hi')).toBe('# Hi')
  })
  it('giữ nguyên khi không có', () => {
    expect(stripFrontMatter('# Hi\n---\nx')).toBe('# Hi\n---\nx')
  })
})
