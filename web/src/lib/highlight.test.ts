import { headingText, pageRange, splitHighlight } from './highlight'

describe('splitHighlight', () => {
  it('đánh dấu từ khoá không phân biệt hoa thường', () => {
    expect(splitHighlight('Doanh thu quý 3, doanh THU tăng', 'doanh thu')).toEqual([
      { text: 'Doanh', hit: true },
      { text: ' ', hit: false },
      { text: 'thu', hit: true },
      { text: ' quý 3, ', hit: false },
      { text: 'doanh', hit: true },
      { text: ' ', hit: false },
      { text: 'THU', hit: true },
      { text: ' tăng', hit: false },
    ])
  })
  it('text bắt đầu bằng ký tự không khớp vẫn đúng', () => {
    expect(splitHighlight('xin chào abc', 'abc')).toEqual([
      { text: 'xin chào ', hit: false },
      { text: 'abc', hit: true },
    ])
  })
  it('ký tự regex trong query được escape', () => {
    expect(splitHighlight('a (b) c', '(b)')).toEqual([
      { text: 'a ', hit: false },
      { text: '(b)', hit: true },
      { text: ' c', hit: false },
    ])
  })
  it('query rỗng hoặc chỉ từ 1 ký tự thì không đánh dấu', () => {
    expect(splitHighlight('abc', '  ')).toEqual([{ text: 'abc', hit: false }])
    expect(splitHighlight('abc', 'a')).toEqual([{ text: 'abc', hit: false }])
  })
})

describe('headingText, pageRange', () => {
  it('nối mảng', () => expect(headingText(['A', 'B'])).toBe('A › B'))
  it('chuỗi', () => expect(headingText('A')).toBe('A'))
  it('trang', () => {
    expect(pageRange(0, 0)).toBe('')
    expect(pageRange(2, 2)).toBe('trang 2')
    expect(pageRange(2, 4)).toBe('trang 2–4')
  })
})
