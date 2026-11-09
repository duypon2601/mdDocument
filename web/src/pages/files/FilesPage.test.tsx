import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { MemoryRouter, useLocation } from 'react-router'
import { ToastProvider } from '../../components/Toast'
import { doc, sampleDocs } from '../../test/handlers'
import { server } from '../../test/server'
import { FilesPage } from './FilesPage'

function Where() {
  const l = useLocation()
  return <output data-testid="where">{l.pathname + l.search}</output>
}

function at(path = '/files') {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={qc}>
      <ToastProvider>
        <MemoryRouter initialEntries={[path]}>
          <FilesPage />
          <Where />
        </MemoryRouter>
      </ToastProvider>
    </QueryClientProvider>,
  )
}

const where = () => screen.getByTestId('where').textContent

function mockFetchUpload(responses: Response[]) {
  const real = globalThis.fetch
  const forms: FormData[] = []
  const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.href : input.url
    if (url === '/documents' && init?.method === 'POST') {
      forms.push(init.body as FormData)
      return responses.shift() ?? Response.json({ detail: 'hết mẫu' }, { status: 500 })
    }
    return real(input, init)
  })
  return { forms, spy }
}

afterEach(() => {
  vi.restoreAllMocks()
  localStorage.clear()
})

describe('danh sách', () => {
  it('hiện bảng, tổng số và tag profile', async () => {
    at()
    expect(await screen.findByText('bao-cao-tai-chinh.xlsx')).toBeInTheDocument()
    expect(screen.getByText(/4 tài liệu · Trang 1\/1/)).toBeInTheDocument()
  })

  it('bấm tab ghi trạng thái vào URL và gửi đúng query', async () => {
    let seen = ''
    server.use(
      http.get('/documents', ({ request }) => {
        seen = new URL(request.url).search
        return HttpResponse.json({ items: [], total: 0, limit: 20, offset: 0 })
      }),
    )
    at('/files?page=3')
    await userEvent.click(await screen.findByRole('tab', { name: 'Đang chạy' }))
    await waitFor(() => expect(where()).toBe('/files?status=running'))
    await waitFor(() =>
      expect(new URLSearchParams(seen).get('status')).toBe(
        'RECEIVED,CONVERTING,NEEDS_REVIEW,CONVERTED,INDEXING',
      ),
    )
    expect(screen.getByRole('tab', { name: 'Đang chạy' })).toHaveAttribute('aria-selected', 'true')
  })

  it('đọc bộ lọc từ URL khi tải trang', async () => {
    at('/files?status=FAILED&q=loi')
    expect(await screen.findByText('loi.pdf')).toBeInTheDocument()
    expect(screen.queryByText('hop-dong-scan.pdf')).not.toBeInTheDocument()
    expect(screen.getByRole('tab', { name: 'Lỗi' })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByRole('searchbox')).toHaveValue('loi')
  })

  it('ô tìm ghi vào URL sau khi ngừng gõ', async () => {
    at()
    await screen.findByText('loi.pdf')
    await userEvent.type(screen.getByRole('searchbox'), 'loi')
    expect(where()).toBe('/files')
    await waitFor(() => expect(where()).toBe('/files?q=loi'), { timeout: 2000 })
  })

  it('phân trang 20 dòng và ghi page vào URL', async () => {
    const many = Array.from({ length: 45 }, (_, i) => doc(String(i).padStart(64, '0'), `f${i}.pdf`, 'INDEXED'))
    server.use(
      http.get('/documents', ({ request }) => {
        const u = new URL(request.url)
        const limit = Number(u.searchParams.get('limit'))
        const offset = Number(u.searchParams.get('offset'))
        return HttpResponse.json({ items: many.slice(offset, offset + limit), total: 45, limit, offset })
      }),
    )
    at()
    expect(await screen.findByText('f0.pdf')).toBeInTheDocument()
    expect(screen.getByText(/45 tài liệu · Trang 1\/3/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Trang sau' }))
    expect(await screen.findByText('f20.pdf')).toBeInTheDocument()
    expect(where()).toBe('/files?page=2')
    expect(screen.queryByText('f0.pdf')).not.toBeInTheDocument()
  })

  it('không có kết quả thì báo rỗng', async () => {
    at('/files?q=khongco')
    expect(await screen.findByText('Không có tài liệu phù hợp')).toBeInTheDocument()
  })
})

describe('nút trên dòng', () => {
  it('Dừng gọi cancel sau khi xác nhận', async () => {
    const calls: string[] = []
    server.use(
      http.post('/documents/:id/cancel', ({ params }) => {
        calls.push(String(params.id))
        return HttpResponse.json({ doc_id: params.id, cancel_requested: true }, { status: 202 })
      }),
    )
    at()
    await userEvent.click(await screen.findByRole('button', { name: 'Dừng hop-dong-scan.pdf' }))
    expect(calls).toEqual([])
    const dialog = screen.getByRole('dialog', { hidden: true })
    await userEvent.click(within(dialog).getByRole('button', { name: 'Dừng', hidden: true }))
    await waitFor(() => expect(calls).toEqual([sampleDocs[1].doc_id]))
    expect(await screen.findByText(/Đã gửi yêu cầu dừng/)).toBeInTheDocument()
  })

  it('Quay lại thì không gọi cancel', async () => {
    let called = false
    server.use(
      http.post('/documents/:id/cancel', () => {
        called = true
        return HttpResponse.json({}, { status: 202 })
      }),
    )
    at()
    await userEvent.click(await screen.findByRole('button', { name: 'Dừng hop-dong-scan.pdf' }))
    await userEvent.click(screen.getByRole('button', { name: 'Quay lại', hidden: true }))
    expect(called).toBe(false)
  })

  it('Re-index chỉ có ở INDEXED và gọi đúng endpoint', async () => {
    const calls: string[] = []
    server.use(
      http.post('/documents/:id/reindex', ({ params }) => {
        calls.push(String(params.id))
        return HttpResponse.json({ doc_id: params.id, index_version: 2 }, { status: 202 })
      }),
    )
    at()
    await screen.findByText('loi.pdf')
    expect(screen.getAllByRole('button', { name: /^Re-index / })).toHaveLength(1)
    await userEvent.click(screen.getByRole('button', { name: 'Re-index bao-cao-tai-chinh.xlsx' }))
    await waitFor(() => expect(calls).toEqual([sampleDocs[0].doc_id]))
    expect(await screen.findByText(/Đã yêu cầu re-index/)).toBeInTheDocument()
  })
})

describe('Dừng tất cả ở tab Đang chạy', () => {
  it('chỉ hiện ở tab Đang chạy', async () => {
    at()
    await screen.findByText('loi.pdf')
    expect(screen.queryByRole('button', { name: 'Dừng tất cả đang chạy' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('tab', { name: 'Đang chạy' }))
    expect(await screen.findByRole('button', { name: 'Dừng tất cả đang chạy' })).toBeInTheDocument()
  })
})

describe('upload', () => {
  const pdf = () => new File(['x'], 'moi.pdf', { type: 'application/pdf' })
  const created = { ...doc('e'.repeat(64), 'moi.pdf', 'RECEIVED') }

  it('thành công: gửi field theo profile mặc định v2 và hiện "Đã nhận"', async () => {
    const { forms } = mockFetchUpload([Response.json({ duplicate: false, ...created }, { status: 202 })])
    at()
    await userEvent.upload(screen.getByLabelText('Chọn file để tải lên'), pdf())
    expect(await screen.findByText('Đã nhận')).toBeInTheDocument()
    expect(forms).toHaveLength(1)
    expect(forms[0].get('extract_media')).toBe('true')
    expect(forms[0].get('pipeline_version')).toBe('2')
  })

  it('đổi profile sang bản cũ thì gửi field tương ứng và nhớ lựa chọn', async () => {
    const { forms } = mockFetchUpload([Response.json({ duplicate: false, ...created }, { status: 202 })])
    at()
    await userEvent.click(screen.getByRole('radio', { name: /Bản cũ/ }))
    expect(localStorage.getItem('profile')).toBe('legacy')
    await userEvent.upload(screen.getByLabelText('Chọn file để tải lên'), pdf())
    await screen.findByText('Đã nhận')
    expect(forms[0].get('extract_media')).toBe('false')
    expect(forms[0].get('pipeline_version')).toBe('2')
  })

  it('profile v1 gửi pipeline_version=1', async () => {
    const { forms } = mockFetchUpload([Response.json({ duplicate: false, ...created }, { status: 202 })])
    at()
    await userEvent.click(screen.getByRole('radio', { name: /Mới v1/ }))
    await userEvent.upload(screen.getByLabelText('Chọn file để tải lên'), pdf())
    await screen.findByText('Đã nhận')
    expect(forms[0].get('extract_media')).toBe('true')
    expect(forms[0].get('pipeline_version')).toBe('1')
  })

  it('đọc profile đã nhớ', () => {
    localStorage.setItem('profile', 'v1')
    at()
    expect(screen.getByRole('radio', { name: /Mới v1/ })).toBeChecked()
  })

  it('trùng: báo dùng lại kết quả', async () => {
    mockFetchUpload([Response.json({ duplicate: true, ...created }, { status: 200 })])
    at()
    await userEvent.upload(screen.getByLabelText('Chọn file để tải lên'), pdf())
    expect(await screen.findByText('Trùng, dùng lại kết quả')).toBeInTheDocument()
  })

  it('lỗi 413 hiện detail', async () => {
    mockFetchUpload([Response.json({ detail: 'File quá lớn' }, { status: 413 })])
    at()
    await userEvent.upload(screen.getByLabelText('Chọn file để tải lên'), pdf())
    expect(await screen.findByText('Lỗi: File quá lớn')).toBeInTheDocument()
  })

  it('nhiều file được gửi lần lượt', async () => {
    const { forms } = mockFetchUpload([
      Response.json({ duplicate: false, ...created }, { status: 202 }),
      Response.json({ duplicate: true, ...created }, { status: 200 }),
    ])
    at()
    await userEvent.upload(screen.getByLabelText('Chọn file để tải lên'), [
      new File(['1'], 'a.pdf'),
      new File(['2'], 'b.pdf'),
    ])
    expect(await screen.findByText('Trùng, dùng lại kết quả')).toBeInTheDocument()
    expect(forms.map((f) => (f.get('file') as File).name)).toEqual(['a.pdf', 'b.pdf'])
  })
})
