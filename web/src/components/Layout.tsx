import { NavLink, Outlet } from 'react-router'

const LINKS = [
  { to: '/', label: 'Tổng quan', end: true },
  { to: '/files', label: 'Tài liệu', end: false },
  { to: '/search', label: 'Tìm kiếm thử', end: false },
]

export function Layout() {
  return (
    <div className="min-h-dvh">
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
      <main className="mx-auto max-w-6xl px-4 py-6">
        <Outlet />
      </main>
    </div>
  )
}
