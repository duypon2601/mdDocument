import { Suspense } from 'react'
import { NavLink, Outlet, useLocation } from 'react-router'
import { ConnectionBanner } from './ConnectionBanner'
import { RouteErrorBoundary } from './RouteErrorBoundary'
import { Skeleton } from './Skeleton'

const LINKS = [
  { to: '/', label: 'Tổng quan', end: true },
  { to: '/files', label: 'Tài liệu', end: false },
  { to: '/search', label: 'Tìm kiếm thử', end: false },
]

export function Layout() {
  const { pathname } = useLocation()
  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2"
      >
        Bỏ qua điều hướng
      </a>
      <ConnectionBanner />
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2">
          <span className="font-semibold">Ingestion</span>
          <nav aria-label="Điều hướng chính" className="flex flex-wrap gap-1">
            {LINKS.map((l) => (
              <NavLink
                key={l.to}
                to={l.to}
                end={l.end}
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-medium ${
                    isActive ? 'bg-surface-2 text-fg' : 'text-muted hover:bg-surface-2'
                  }`
                }
              >
                {l.label}
              </NavLink>
            ))}
          </nav>
        </div>
      </header>
      <main id="main" className="mx-auto max-w-6xl px-4 py-6">
        <RouteErrorBoundary resetKey={pathname}>
          <Suspense fallback={<Skeleton rows={4} />}>
            <Outlet />
          </Suspense>
        </RouteErrorBoundary>
      </main>
    </div>
  )
}
