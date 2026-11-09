import { Link } from 'react-router'
import { useDocumentTitle } from '../lib/useDocumentTitle'
import { EmptyState } from '../components/EmptyState'

export function NotFoundPage() {
  useDocumentTitle('Không tìm thấy trang')
  return (
    <EmptyState
      title="Không tìm thấy trang"
      action={
        <Link to="/" className="text-accent underline">
          Về trang tổng quan
        </Link>
      }
    />
  )
}
