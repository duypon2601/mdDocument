import { Link } from 'react-router'
import { EmptyState } from '../components/EmptyState'

export function NotFoundPage() {
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
