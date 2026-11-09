import { useParams } from 'react-router'
import { EmptyState } from '../components/EmptyState'

function Page({ title, children }: { title: string; children?: string }) {
  return (
    <section>
      <h1 className="mb-4 text-2xl font-semibold">{title}</h1>
      <EmptyState title="Màn hình đang được xây dựng">{children}</EmptyState>
    </section>
  )
}

export function DashboardPage() {
  return <Page title="Tổng quan" />
}

export function DocumentPage() {
  const { docId } = useParams()
  return <Page title="Chi tiết tài liệu">{docId}</Page>
}

export function SearchPage() {
  return <Page title="Tìm kiếm thử" />
}
