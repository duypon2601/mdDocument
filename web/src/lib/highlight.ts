export interface Segment {
  text: string
  hit: boolean
}

/** Chia text thành các đoạn, đánh dấu đoạn khớp từ khoá thô (tách theo khoảng trắng, không phân biệt hoa thường). */
export function splitHighlight(text: string, query: string): Segment[] {
  const terms = [...new Set(query.trim().split(/\s+/).filter((t) => t.length >= 2))]
  if (!text || terms.length === 0) return [{ text, hit: false }]
  terms.sort((a, b) => b.length - a.length)
  const re = new RegExp(`(${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')})`, 'giu')
  return text
    .split(re)
    .map((s, i) => ({ text: s, hit: i % 2 === 1 }))
    .filter((s) => s.text !== '')
}

/** heading_path có thể là mảng hoặc chuỗi. */
export function headingText(h: string[] | string | null | undefined): string {
  if (!h) return ''
  return Array.isArray(h) ? h.join(' › ') : h
}

export function pageRange(start: number, end: number): string {
  if (!start) return ''
  return end && end !== start ? `trang ${start}–${end}` : `trang ${start}`
}
