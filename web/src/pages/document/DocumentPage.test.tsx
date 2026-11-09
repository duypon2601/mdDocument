import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes } from 'react-router'
import type { Status } from '../../api/types'
import { ToastProvider } from '../../components/Toast'
import { doc } from '../../test/handlers'
import { server } from '../../test/server'
import { DocumentPage } from './DocumentPage'

const ID = 'f'.repeat(64)

function open(status: Status, extra = {}, progress: string | null = null, path = `/files/${ID}`) {
  server.use(
    http.get('/documents/:id', ({ params }) =>
      params.id === ID
        ? HttpResponse.json({ ...doc(ID, 'bao-cao.pdf', status, extra), progress })
        : HttpResponse.json({ detail: 'Không tìm thấy' }, { status: 404 }),
    ),
  )
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <Routes>
            <Route path="/files" element={<p>danh sách</p>} />
            <Route path="/files/:docId" element={<DocumentPage />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const buttons = () =>
  screen
    .queryAllByRole('button')
    .map((b) => b.textContent)
    .filter((t) => ['Duyệt', 'Từ chối', 'Dừng', 'Re-index', 'Tải Markdown'].includes(t ?? ''))

describe('nút theo trạng thái', () => {
  const cases: [Status, string[]][] = [
    ['RECEIVED', ['Dừng']],
    ['CONVERTING', ['Dừng']],
    ['CONVERTED', ['Dừng']],
    ['INDEXING', ['Dừng']],
    ['NEEDS_REVIEW', ['Duyệt', 'Từ chối', 'Dừng']],
    ['INDEXED', ['Re-index', 'Tải Markdown']],
    ['FAILED', []],
    ['CANCELLED', []],
  ]
  it.each(cases)('%s', async (status, expected) => {
    open(status)
    await screen.findByRole('heading', { name: 'bao-cao.pdf' })
    expect(buttons()).toEqual(expected)
    const raw = screen.getByRole('link', { name: 'Tải file gốc' })
    expect(raw).toHaveAttribute('href', `/documents/${ID}/raw`)
    expect(raw).toHaveAttribute('download')
  })
})

describe('hành động', () => {
  it('Dừng hỏi xác nhận rồi gọi cancel', async () => {
    let called = false
    server.use(
      http.post('/documents/:id/cancel', ({ params }) => {
        called = true
        return HttpResponse.json({ doc_id: params.id, cancel_requested: true }, { status: 202 })
      }),
    )
    open('CONVERTING')
    await userEvent.click(await screen.findByRole('button', { name: 'Dừng' }))
    expect(called).toBe(false)
    const dialog = await screen.findByRole('dialog', { name: 'Dừng xử lý tài liệu?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Dừng' }))
    await waitFor(() => expect(called).toBe(true))
    expect(await screen.findByText(/Đã gửi yêu cầu dừng/)).toBeInTheDocument()
  })

  it('Duyệt gọi review approve không cần xác nhận, Từ chối cần', async () => {
    const seen: (string | null)[] = []
    server.use(
      http.post('/documents/:id/review', ({ request }) => {
        seen.push(new URL(request.url).searchParams.get('decision'))
        return HttpResponse.json({})
      }),
    )
    open('NEEDS_REVIEW')
    await userEvent.click(await screen.findByRole('button', { name: 'Duyệt' }))
    await waitFor(() => expect(seen).toEqual(['approve']))
    await userEvent.click(screen.getByRole('button', { name: 'Từ chối' }))
    const dialog = await screen.findByRole('dialog', { name: 'Từ chối tài liệu?' })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Từ chối' }))
    await waitFor(() => expect(seen).toEqual(['approve', 'reject']))
  })

  it('Re-index gọi endpoint reindex', async () => {
    let called = false
    server.use(
      http.post('/documents/:id/reindex', () => {
        called = true
        return HttpResponse.json({ doc_id: ID, index_version: 2 }, { status: 202 })
      }),
    )
    open('INDEXED')
    await userEvent.click(await screen.findByRole('button', { name: 'Re-index' }))
    await waitFor(() => expect(called).toBe(true))
  })
})

describe('timeline', () => {
  it('đánh dấu bước hiện tại theo progress', async () => {
    open('RECEIVED', {}, 'INDEXING')
    await screen.findByRole('heading', { name: 'bao-cao.pdf' })
    const cur = document.querySelector('[aria-current="step"]')!
    expect(cur).toHaveTextContent('Đang index')
  })

  it('tô đỏ khi FAILED', async () => {
    open('FAILED', { error_code: 'OCR_FAILED' })
    await screen.findByRole('heading', { name: 'bao-cao.pdf' })
    expect(document.querySelector('[data-state="failed"]')).toHaveTextContent('Đang chuyển đổi')
  })
})

describe('tab Markdown', () => {
  it('render bảng, bỏ front-matter, loại script', async () => {
    server.use(
      http.get('/documents/:id/markdown', () =>
        HttpResponse.text(
          '---\ntitle: x\n---\n\n# Báo cáo\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n<script>window.hacked=1</script>\n\n<img src=x onerror="window.hacked=1">',
        ),
      ),
    )
    open('INDEXED')
    expect(await screen.findByRole('table')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Báo cáo' })).toBeInTheDocument()
    expect(screen.queryByText(/title: x/)).not.toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
    expect(document.querySelector('[onerror]')).toBeNull()
  })

  it('Xem gốc hiện pre', async () => {
    server.use(
      http.get('/documents/:id/markdown', () => HttpResponse.text('| a | b |\n|---|---|\n| 1 | 2 |')),
    )
    open('INDEXED')
    await screen.findByRole('table')
    await userEvent.click(screen.getByRole('button', { name: 'Xem gốc' }))
    expect(document.querySelector('pre')?.textContent).toContain('| a | b |')
  })

  it('404 là thông báo bình thường, không phải lỗi đỏ', async () => {
    server.use(
      http.get('/documents/:id/markdown', () =>
        HttpResponse.json({ detail: 'chưa có' }, { status: 404 }),
      ),
    )
    open('NEEDS_REVIEW')
    expect(await screen.findByText('Chưa có Markdown cho tài liệu này.')).toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('đang chuyển đổi thì không gọi markdown', async () => {
    let hit = false
    server.use(
      http.get('/documents/:id/markdown', () => {
        hit = true
        return HttpResponse.text('x')
      }),
    )
    open('CONVERTING')
    expect(await screen.findByText('Markdown sẽ hiện khi chuyển đổi xong.')).toBeInTheDocument()
    expect(hit).toBe(false)
  })

  it('FAILED báo kèm error_code', async () => {
    server.use(
      http.get('/documents/:id/markdown', () => HttpResponse.json({ detail: 'x' }, { status: 404 })),
    )
    open('FAILED', { error_code: 'OCR_FAILED' })
    expect(await screen.findByText(/Mã lỗi: OCR_FAILED/)).toBeInTheDocument()
  })
})

describe('tab Thông tin', () => {
  it('hiện doc_id đầy đủ và copy được', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true })
    open('INDEXED', { chunk_count: 7 }, null, `/files/${ID}?tab=info`)
    expect(await screen.findByText(ID)).toBeInTheDocument()
    expect(screen.getByText('bge-m3')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Copy' }))
    expect(writeText).toHaveBeenCalledWith(ID)
    expect(await screen.findByRole('button', { name: 'Đã copy' })).toBeInTheDocument()
  })

  it('chuyển tab ghi lên URL', async () => {
    open('INDEXED')
    await userEvent.click(await screen.findByRole('tab', { name: 'Thông tin' }))
    expect(screen.getByRole('tab', { name: 'Thông tin' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('index_version')).toBeInTheDocument()
  })
})

describe('Tìm trong tài liệu này', () => {
  it('chỉ hiện khi INDEXED và trỏ tới /search?doc_id=', async () => {
    open('INDEXED')
    const link = await screen.findByRole('link', { name: 'Tìm trong tài liệu này' })
    expect(link).toHaveAttribute('href', `/search?doc_id=${ID}`)
  })
  it('không hiện khi chưa INDEXED', async () => {
    open('CONVERTING')
    await screen.findByRole('heading', { name: 'bao-cao.pdf' })
    expect(screen.queryByRole('link', { name: 'Tìm trong tài liệu này' })).toBeNull()
  })
})

describe('không tìm thấy', () => {
  it('hiện trang 404 có link về /files', async () => {
    open('INDEXED', {}, null, '/files/khong-co')
    expect(await screen.findByText('Không tìm thấy tài liệu')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('link', { name: 'Về danh sách tài liệu' }))
    expect(await screen.findByText('danh sách')).toBeInTheDocument()
  })
})

describe('tab Markdown khi trạng thái đổi', () => {
  it('tải lại Markdown khi tài liệu từ NEEDS_REVIEW sang INDEXED', async () => {
    let status: Status = 'NEEDS_REVIEW'
    let updated = '2026-01-01T00:00:00Z'
    server.use(
      http.get('/documents/:id', () =>
        HttpResponse.json({
          ...doc(ID, 'bao-cao.pdf', status, { updated_at: updated }),
          progress: null,
        }),
      ),
      http.get('/documents/:id/markdown', () =>
        status === 'INDEXED'
          ? HttpResponse.text('# Đã có')
          : HttpResponse.json({ detail: 'chưa có' }, { status: 404 }),
      ),
    )
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={qc}>
        <ToastProvider>
          <MemoryRouter initialEntries={[`/files/${ID}`]}>
            <Routes>
              <Route path="/files/:docId" element={<DocumentPage />} />
            </Routes>
          </MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>,
    )
    expect(await screen.findByText('Chưa có Markdown cho tài liệu này.')).toBeInTheDocument()
    status = 'INDEXED'
    updated = '2026-01-01T00:01:00Z'
    await qc.invalidateQueries({ queryKey: ['documents', 'detail'] })
    expect(await screen.findByRole('heading', { name: 'Đã có' })).toBeInTheDocument()
  })
})
