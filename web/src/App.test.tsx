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
    ['/files/abc', 'Chi tiết tài liệu'],
    ['/search', 'Tìm kiếm thử'],
  ])('%s có trang placeholder', (path, heading) => {
    at(path)
    expect(screen.getByRole('heading', { level: 1, name: heading })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Điều hướng chính' })).toBeInTheDocument()
  })

  it('đường dẫn lạ hiện trang 404', () => {
    at('/khong-co')
    expect(screen.getByText('Không tìm thấy trang')).toBeInTheDocument()
  })
})
