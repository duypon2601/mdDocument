import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { ConnectionBanner } from '../../components/ConnectionBanner'
import { ToastProvider } from '../../components/Toast'
import { sampleDocs, sampleStats } from '../../test/handlers'
import { server } from '../../test/server'
import { DashboardPage } from './DashboardPage'

function Where() {
  const l = useLocation()
  return <output data-testid="where">{l.pathname + l.search}</output>
}

function at(path = '/') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <ConnectionBanner />
          <Routes>
            <Route path="/" element={<DashboardPage />} />
            <Route path="*" element={<Where />} />
          </Routes>
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe('dashboard', () => {
  it('đếm đúng theo trạng thái và tổng chunk', async () => {
    at()
    const running = await screen.findByRole('link', { name: /Đang chạy/ })
    // mẫu: CONVERTING 1 + NEEDS_REVIEW 1 = 2
    expect(running).toHaveTextContent('2')
    expect(screen.getByRole('link', { name: /Hoàn tất/ })).toHaveTextContent('1')
    expect(screen.getByRole('link', { name: /Lỗi/ })).toHaveTextContent('1')
    expect(screen.getByText('Tổng chunk').parentElement).toHaveTextContent('12')
    expect(screen.getByText('Tổng tài liệu').parentElement).toHaveTextContent(String(sampleDocs.length))
  })

  it('bấm thẻ mở /files theo trạng thái', async () => {
    at()
    await userEvent.click(await screen.findByRole('link', { name: /Lỗi/ }))
    expect(screen.getByTestId('where')).toHaveTextContent('/files?status=FAILED')
  })

  it('liệt kê tài liệu mới nhất', async () => {
    at()
    expect(await screen.findByRole('link', { name: 'loi.pdf' })).toHaveAttribute(
      'href',
      `/files/${sampleDocs[3].doc_id}`,
    )
  })

  it('đặt tiêu đề tab', async () => {
    at()
    await screen.findByRole('link', { name: /Đang chạy/ })
    expect(document.title).toBe('Tổng quan · Ingestion')
  })

  it('lỗi stats có nút thử lại', async () => {
    let fail = true
    server.use(
      http.get('/stats', () =>
        fail ? HttpResponse.json({ detail: 'hỏng' }, { status: 500 }) : HttpResponse.json(sampleStats()),
      ),
    )
    at()
    expect(await screen.findByText('hỏng')).toBeInTheDocument()
    fail = false
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    expect(await screen.findByRole('link', { name: /Hoàn tất/ })).toBeInTheDocument()
  })
})

describe('Dừng tất cả', () => {
  it('xác nhận ghi rõ số tài liệu, gọi API và báo kết quả kèm lỗi', async () => {
    let called = 0
    server.use(
      http.post('/documents/cancel-running', () => {
        called++
        return HttpResponse.json(
          { requested: ['a'.repeat(64)], failed: [{ doc_id: 'b'.repeat(64), detail: 'đã xong' }] },
          { status: 202 },
        )
      }),
    )
    at()
    await userEvent.click(await screen.findByRole('button', { name: 'Dừng tất cả đang chạy' }))
    const dialog = screen.getByRole('dialog', { hidden: true })
    expect(dialog).toHaveTextContent('2 tài liệu đang chạy')
    expect(called).toBe(0)
    await userEvent.click(within(dialog).getByRole('button', { name: 'Dừng 2 tài liệu', hidden: true }))
    expect(await screen.findByText('Đã gửi lệnh dừng 1 tài liệu')).toBeInTheDocument()
    expect(screen.getByText(/1 tài liệu không dừng được: bbbbbbbb \(đã xong\)/)).toBeInTheDocument()
    expect(called).toBe(1)
  })

  it('không hiện nút khi không có tài liệu chạy', async () => {
    server.use(
      http.get('/stats', () => {
        const s = sampleStats()
        s.by_status.CONVERTING = 0
        s.by_status.NEEDS_REVIEW = 0
        return HttpResponse.json(s)
      }),
    )
    at()
    await screen.findByRole('link', { name: /Hoàn tất/ })
    expect(screen.queryByRole('button', { name: 'Dừng tất cả đang chạy' })).not.toBeInTheDocument()
  })
})

describe('banner mất kết nối', () => {
  it('hiện khi fetch lỗi mạng và tự hết khi API có lại', async () => {
    let down = true
    server.use(
      http.get('/stats', () => (down ? HttpResponse.error() : HttpResponse.json(sampleStats()))),
    )
    at()
    expect(await screen.findByText(/Mất kết nối API/)).toBeInTheDocument()
    down = false
    await userEvent.click(screen.getByRole('button', { name: 'Thử lại' }))
    await waitFor(() => expect(screen.queryByText(/Mất kết nối API/)).not.toBeInTheDocument())
  })
})
