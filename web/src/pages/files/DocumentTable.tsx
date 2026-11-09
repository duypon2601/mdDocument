import { Link, useNavigate } from 'react-router'
import type { Document } from '../../api/types'
import { Button } from '../../components/Button'
import { StatusPill } from '../../components/StatusPill'
import { formatSize, formatTime } from '../../lib/format'
import { PROFILE_LABEL, profileOf } from '../../lib/profile'
import { isRunning } from '../../lib/status'

interface Props {
  items: Document[]
  onStop: (d: Document) => void
  onReindex: (d: Document) => void
  busyId?: string | null
}

/** Bảng ở màn rộng, mỗi dòng thành một thẻ ở màn hẹp (CSS, cùng một cấu trúc DOM). */
export function DocumentTable({ items, onStop, onReindex, busyId }: Props) {
  const navigate = useNavigate()
  const cell = 'px-3 py-2 max-md:flex max-md:justify-between max-md:gap-3 max-md:py-1'
  const label = 'text-muted md:hidden'

  return (
    <table className="w-full text-left text-sm max-md:block">
      <thead className="max-md:sr-only">
        <tr className="border-b border-line text-muted">
          <th className="px-3 py-2 font-medium">Tên file</th>
          <th className="px-3 py-2 font-medium">Kích thước</th>
          <th className="px-3 py-2 font-medium">Trạng thái</th>
          <th className="px-3 py-2 text-right font-medium">Chunk</th>
          <th className="px-3 py-2 font-medium">Cập nhật lúc</th>
          <th className="px-3 py-2 font-medium">
            <span className="sr-only">Thao tác</span>
          </th>
        </tr>
      </thead>
      <tbody className="max-md:block">
        {items.map((d) => {
          const p = profileOf(d)
          return (
            <tr
              key={d.doc_id}
              onClick={() => navigate(`/files/${d.doc_id}`)}
              className="cursor-pointer border-b border-line hover:bg-surface-2 max-md:mb-3 max-md:block max-md:rounded-lg max-md:border max-md:p-2"
            >
              <td className={`${cell} max-md:block`}>
                <Link
                  to={`/files/${d.doc_id}`}
                  onClick={(e) => e.stopPropagation()}
                  className="font-medium break-all text-accent hover:underline"
                >
                  {d.file_name}
                </Link>
                <span
                  title="Kiểu xử lý lúc upload"
                  className={`ml-2 rounded px-1.5 py-0.5 text-xs ${p === 'legacy' ? 'bg-warn-bg text-warn-fg' : 'bg-surface-2 text-muted'}`}
                >
                  {PROFILE_LABEL[p]}
                </span>
              </td>
              <td className={cell}>
                <span className={label}>Kích thước</span>
                {formatSize(d.size)}
              </td>
              <td className={cell}>
                <span className={label}>Trạng thái</span>
                <StatusPill status={d.status} />
              </td>
              <td className={`${cell} md:text-right`}>
                <span className={label}>Chunk</span>
                {d.chunk_count}
              </td>
              <td className={cell}>
                <span className={label}>Cập nhật lúc</span>
                {formatTime(d.updated_at)}
              </td>
              <td className={`${cell} md:text-right`}>
                <span className="inline-flex gap-2" onClick={(e) => e.stopPropagation()}>
                  {isRunning(d.status) && (
                    <Button
                      variant="danger"
                      disabled={busyId === d.doc_id}
                      aria-label={`Dừng ${d.file_name}`}
                      onClick={() => onStop(d)}
                    >
                      Dừng
                    </Button>
                  )}
                  {d.status === 'INDEXED' && (
                    <Button
                      disabled={busyId === d.doc_id}
                      aria-label={`Re-index ${d.file_name}`}
                      onClick={() => onReindex(d)}
                    >
                      Re-index
                    </Button>
                  )}
                </span>
              </td>
            </tr>
          )
        })}
      </tbody>
    </table>
  )
}
