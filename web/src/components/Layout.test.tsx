import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { Layout } from './Layout'

function Boom(): never {
  throw new Error('chunk hỏng')
}

it('lỗi render trong trang hiện ErrorState thay vì trắng màn hình', () => {
  vi.spyOn(console, 'error').mockImplementation(() => {})
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <MemoryRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Boom />} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
  expect(screen.getByText('Không hiển thị được trang này')).toBeInTheDocument()
  expect(screen.getByText('chunk hỏng')).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Thử lại' })).toBeInTheDocument()
})
