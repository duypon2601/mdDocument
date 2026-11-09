import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy } from 'react'
import { Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toast'
import { NotFoundPage } from './pages/NotFound'

// Mỗi trang là một chunk riêng để bundle chính nhỏ (DocumentPage kéo theo react-markdown).
const DashboardPage = lazy(() =>
  import('./pages/dashboard/DashboardPage').then((m) => ({ default: m.DashboardPage })),
)
const FilesPage = lazy(() => import('./pages/files/FilesPage').then((m) => ({ default: m.FilesPage })))
const DocumentPage = lazy(() =>
  import('./pages/document/DocumentPage').then((m) => ({ default: m.DocumentPage })),
)
const SearchPage = lazy(() => import('./pages/search/SearchPage').then((m) => ({ default: m.SearchPage })))

export function makeQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { staleTime: 1000, refetchOnWindowFocus: true } },
  })
}

const queryClient = makeQueryClient()

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<DashboardPage />} />
            <Route path="files" element={<FilesPage />} />
            <Route path="files/:docId" element={<DocumentPage />} />
            <Route path="search" element={<SearchPage />} />
            <Route path="*" element={<NotFoundPage />} />
          </Route>
        </Routes>
      </ToastProvider>
    </QueryClientProvider>
  )
}
