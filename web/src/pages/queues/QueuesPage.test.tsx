import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { MemoryRouter } from 'react-router'
import { QueueStrip } from '../../components/QueueStrip'
import { sampleDocs } from '../../test/handlers'
import { server } from '../../test/server'
import { QueuesPage } from './QueuesPage'

function show(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('trang Hàng đợi', () => {
  it('đánh dấu queue thiếu worker và đếm task chờ', async () => {
    show(<QueuesPage />)
    const convert = await screen.findByRole('listitem', { name: 'Queue convert-tq' })
    expect(within(convert).getByText('Thiếu worker')).toBeInTheDocument()
    expect(within(convert).getByText('3')).toBeInTheDocument()
    expect(within(convert).getByText('42 giây')).toBeInTheDocument()

    const index = screen.getByRole('listitem', { name: 'Queue index-tq' })
    // index-tq không chạy workflow nên thiếu worker phần workflow vẫn là sẵn sàng
    expect(within(index).getByText('Sẵn sàng')).toBeInTheDocument()
    expect(within(index).queryByText('Workflow task')).not.toBeInTheDocument()
  })

  it('liệt kê workflow đang chạy cùng activity đang chờ', async () => {
    show(<QueuesPage />)
    const link = await screen.findByRole('link', { name: sampleDocs[1].file_name })
    expect(link).toHaveAttribute('href', `/files/${sampleDocs[1].doc_id}`)
    expect(screen.getByText('ocr_pages')).toBeInTheDocument()
    expect(screen.getByText('Chờ worker')).toBeInTheDocument()
    expect(screen.getByText('lần thử 2')).toBeInTheDocument()
    expect(screen.getByText('Lỗi lần trước: timeout')).toBeInTheDocument()
    expect(screen.getByText('chạy được 2 phút')).toBeInTheDocument()
  })

  it('báo lỗi khi không đọc được Temporal', async () => {
    server.use(
      http.get('/temporal/queues', () =>
        HttpResponse.json({ code: 'TEMPORAL_UNAVAILABLE', detail: 'mất kết nối' }, { status: 503 }),
      ),
    )
    show(<QueuesPage />)
    expect(await screen.findByText('Không đọc được Temporal')).toBeInTheDocument()
    expect(screen.getByText('mất kết nối')).toBeInTheDocument()
  })
})

describe('thanh queue trên header', () => {
  it('tóm tắt từng queue và trỏ tới /queues', async () => {
    show(<QueueStrip />)
    const strip = await screen.findByRole('link', { name: /Tình trạng hàng đợi/ })
    expect(strip).toHaveAttribute('href', '/queues')
    expect(strip).toHaveTextContent('convert0w · 3 chờ')
    expect(strip).toHaveTextContent('ingest1w')
    expect(strip).toHaveTextContent('1 đang chạy')
  })
})
