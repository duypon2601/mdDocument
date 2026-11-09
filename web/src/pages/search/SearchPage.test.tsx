import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, useLocation } from 'react-router'
import { sampleDocs } from '../../test/handlers'
import { server } from '../../test/server'
import { SearchPage } from './SearchPage'

function Loc() {
  const l = useLocation()
  return <p data-testid="loc">{l.search}</p>
}

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <SearchPage />
        <Loc />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('trang tìm kiếm', () => {
  it('gửi đúng body và lưu tham số lên URL', async () => {
    const bodies: unknown[] = []
    server.use(
      http.post('/search', async ({ request }) => {
        const b = await request.json()
        bodies.push(b)
        return HttpResponse.json({
          query: 'doanh thu',
          model: 'bge-m3',
          results: [
            {
              score: 0.874, doc_id: sampleDocs[0].doc_id, file_name: 'bao-cao-tai-chinh.xlsx',
              index_version: 1, chunk_index: 3, heading_path: ['Báo cáo', 'Doanh thu'],
              page_start: 2, page_end: 2, text: 'Doanh thu quý 3 tăng 12%.',
            },
          ],
        })
      }),
    )
    renderAt('/search')
    await screen.findByRole('option', { name: 'bao-cao-tai-chinh.xlsx' })
    await userEvent.type(screen.getByLabelText('Câu hỏi'), 'doanh thu{Enter}')
    expect(await screen.findByText('0.87')).toBeInTheDocument()
    expect(bodies).toEqual([{ query: 'doanh thu', top_k: 8, doc_id: null }])
    expect(screen.getByTestId('loc')).toHaveTextContent('?q=doanh+thu')
    expect(screen.getByRole('link', { name: 'bao-cao-tai-chinh.xlsx' })).toHaveAttribute(
      'href',
      `/files/${sampleDocs[0].doc_id}`,
    )
    expect(screen.getByText('trang 2')).toBeInTheDocument()
    const marks = document.querySelectorAll('mark')
    expect([...marks].map((m) => m.textContent)).toEqual(['Doanh', 'thu'])

    await userEvent.selectOptions(screen.getByLabelText('Số kết quả'), '20')
    await userEvent.selectOptions(screen.getByLabelText('Tài liệu'), sampleDocs[0].doc_id)
    await screen.findByText('0.87')
    expect(bodies.at(-1)).toEqual({ query: 'doanh thu', top_k: 20, doc_id: sampleDocs[0].doc_id })
  })

  it('đọc q, k, doc_id từ URL và tự tìm', async () => {
    const bodies: unknown[] = []
    server.use(
      http.post('/search', async ({ request }) => {
        bodies.push(await request.json())
        return HttpResponse.json({ query: 'x', model: 'm', results: [] })
      }),
    )
    renderAt(`/search?q=hop+dong&k=5&doc_id=${sampleDocs[0].doc_id}`)
    expect(await screen.findByText('Không có kết quả')).toBeInTheDocument()
    expect(bodies).toEqual([{ query: 'hop dong', top_k: 5, doc_id: sampleDocs[0].doc_id }])
  })

  it('503 hiện thông báo chưa bật tìm kiếm kèm detail', async () => {
    server.use(
      http.post('/search', () =>
        HttpResponse.json({ code: 'SEARCH_UNAVAILABLE', detail: 'Không gọi được embedding' }, { status: 503 }),
      ),
    )
    renderAt('/search?q=abc')
    expect(await screen.findByText(/Chưa bật tìm kiếm: kiểm tra Qdrant/)).toBeInTheDocument()
    expect(screen.getByText('Không gọi được embedding')).toBeInTheDocument()
  })

  it('highlight không chèn HTML thô', async () => {
    server.use(
      http.post('/search', () =>
        HttpResponse.json({
          query: 'img',
          model: 'm',
          results: [
            {
              score: 0.5, doc_id: 'd', file_name: 'x.pdf', index_version: 1, chunk_index: 0,
              heading_path: '', page_start: 0, page_end: 0,
              text: 'xin <img src=x onerror=alert(1)> chào <script>alert(2)</script>',
            },
          ],
        }),
      ),
    )
    renderAt('/search?q=img+script')
    expect(await screen.findByText('0.50')).toBeInTheDocument()
    expect(document.querySelector('img')).toBeNull()
    expect(document.querySelector('script')).toBeNull()
    expect(document.querySelector('li p')?.textContent).toBe(
      'xin <img src=x onerror=alert(1)> chào <script>alert(2)</script>',
    )
  })
})
