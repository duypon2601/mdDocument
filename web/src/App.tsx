import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toast'
import { NotFoundPage } from './pages/NotFound'
import { FilesPage } from './pages/files/FilesPage'
import { DashboardPage, DocumentPage, SearchPage } from './pages/Placeholder'

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
