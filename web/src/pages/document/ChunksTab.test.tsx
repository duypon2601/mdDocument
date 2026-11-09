import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import type { DocumentDetail } from '../../api/types'
import { doc } from '../../test/handlers'
import { server } from '../../test/server'
import { ChunksTab } from './ChunksTab'

const ID = 'f'.repeat(64)

function renderTab(extra: Partial<DocumentDetail> = {}) {
  const d = { ...doc(ID, 'a.pdf', 'INDEXED', extra), progress: null } as DocumentDetail
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ChunksTab doc={d} />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

function chunkHandler(calls: URL[], total = 120) {
  server.use(
    http.get('/documents/:id/chunks', ({ request }) => {
      const url = new URL(request.url)
      calls.push(url)
      const offset = Number(url.searchParams.get('offset'))
      const limit = Number(url.searchParams.get('limit'))
      const n = Math.max(0, Math.min(limit, total - offset))
      return HttpResponse.json({
        doc_id: ID,
        index_version: Number(url.searchParams.get('version')),
        total,
        offset,
        limit,
        items: Array.from({ length: n }, (_, i) => ({
          chunk_index: offset + i,
          text: i === 0 ? ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'].join('\n') : `đoạn ${offset + i}`,
          heading_path: ['Báo cáo', 'Mục'],
          page_start: i === 1 ? 0 : 2,
          page_end: i === 1 ? 0 : 3,
          content_hash: 'h',
        })),
      })
    }),
  )
}

describe('tab Chunk', () => {
  it('index_version 0 thì báo chưa có chunk và không gọi API', async () => {
    const calls: URL[] = []
    chunkHandler(calls)
    renderTab({ index_version: 0, status: 'CONVERTING' })
    expect(await screen.findByText('Chưa có chunk')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })

  it('phân trang 50, trang, heading, Xem hết', async () => {
    const calls: URL[] = []
    chunkHandler(calls)
    renderTab({ chunk_count: 120 })
    expect(await screen.findByText('#0')).toBeInTheDocument()
    expect(calls[0].searchParams.get('limit')).toBe('50')
    expect(calls[0].searchParams.get('version')).toBe('1')
    expect(screen.getByText('1–50 / 120 chunk')).toBeInTheDocument()
    expect(screen.getAllByText('Báo cáo › Mục').length).toBeGreaterThan(0)
    expect(screen.getAllByText('trang 2–3').length).toBeGreaterThan(0)
    // chunk #1 có page 0: không hiện trang
    expect(screen.getAllByText(/^trang /)).toHaveLength(49)
    const more = screen.getByRole('button', { name: 'Xem hết' })
    await userEvent.click(more)
    expect(screen.getByRole('button', { name: 'Thu gọn' })).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Sau' }))
    expect(await screen.findByText('#50')).toBeInTheDocument()
    expect(calls.at(-1)!.searchParams.get('offset')).toBe('50')
    expect(screen.getByText('51–100 / 120 chunk')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Trước' })).toBeEnabled()
  })

  it('version cũ 404 thì báo đã dọn sau re-index', async () => {
    server.use(
      http.get('/documents/:id/chunks', ({ request }) => {
        const v = new URL(request.url).searchParams.get('version')
        if (v === '1') return HttpResponse.json({ detail: 'Không có chunk' }, { status: 404 })
        return HttpResponse.json({
          doc_id: ID, index_version: 2, total: 1, offset: 0, limit: 50,
          items: [{ chunk_index: 0, text: 'mới', heading_path: [], page_start: 0, page_end: 0, content_hash: 'h' }],
        })
      }),
    )
    renderTab({ index_version: 2 })
    expect(await screen.findByText('mới')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('Version'), '1')
    expect(await screen.findByText('Đã dọn sau re-index')).toBeInTheDocument()
  })

  it('404 ở version hiện tại không phải lỗi đỏ', async () => {
    server.use(
      http.get('/documents/:id/chunks', () => HttpResponse.json({ detail: 'x' }, { status: 404 })),
    )
    renderTab()
    expect(await screen.findByText('Chưa có chunk')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
