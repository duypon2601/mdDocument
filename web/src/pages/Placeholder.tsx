import { EmptyState } from '../components/EmptyState'

function Page({ title }: { title: string }) {
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">{title}</h1>
      <EmptyState title="Màn hình đang được xây dựng" />
    </section>
  )
}

export function DashboardPage() {
  return <Page title="Tổng quan" />
}
