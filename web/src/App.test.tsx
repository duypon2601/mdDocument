import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { App } from './App'

function at(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  )
}

describe('routes', () => {
  it.each([
    ['/', 'Tổng quan'],
    ['/files', 'Tài liệu'],
    ['/search', 'Tìm kiếm thử'],
  ])('%s hiện đúng trang', async (path, heading) => {
    at(path)
    expect(await screen.findByRole('heading', { level: 1, name: heading })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Điều hướng chính' })).toBeInTheDocument()
  })

  it('/files/abc vào màn hình chi tiết', async () => {
    at('/files/abc')
    expect(await screen.findByText('Không tìm thấy tài liệu')).toBeInTheDocument()
  })

  it('đường dẫn lạ hiện trang 404', async () => {
    at('/khong-co')
    expect(await screen.findByText('Không tìm thấy trang')).toBeInTheDocument()
  })
})
