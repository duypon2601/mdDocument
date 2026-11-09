import { useState } from 'react'
import ReactMarkdown from 'react-markdown'
import rehypeSanitize from 'rehype-sanitize'
import remarkGfm from 'remark-gfm'
import { useMarkdown } from '../../api/hooks'
import type { DocumentDetail } from '../../api/types'
import { Button } from '../../components/Button'
import { ErrorState } from '../../components/ErrorState'
import { Skeleton } from '../../components/Skeleton'
import { stripFrontMatter } from '../../lib/markdown'
import { errText } from '../../hooks/useDocActions'

const WAITING = ['RECEIVED', 'CONVERTING']

export function MarkdownTab({ doc }: { doc: DocumentDetail }) {
  const waiting = WAITING.includes(doc.status)
  const md = useMarkdown(doc.doc_id, !waiting, `${doc.status}|${doc.updated_at}`)
  const [raw, setRaw] = useState(false)

  if (waiting) return <Note>Markdown sẽ hiện khi chuyển đổi xong.</Note>
  if (md.isPending) return <Skeleton rows={6} label="Đang tải Markdown…" />
  if (md.isError) {
    const missing = (md.error as { status?: number }).status === 404
    if (!missing) return <ErrorState detail={errText(md.error)} onRetry={() => md.refetch()} />
    if (doc.status === 'FAILED')
      return <Note>Chuyển đổi lỗi nên chưa có Markdown. Mã lỗi: {doc.error_code ?? 'không rõ'}.</Note>
    if (doc.status === 'CANCELLED') return <Note>Tài liệu đã huỷ, chưa có Markdown.</Note>
    return <Note>Chưa có Markdown cho tài liệu này.</Note>
  }

  const text = stripFrontMatter(md.data)
  return (
    <div>
      <div className="mb-3 flex justify-end">
        <Button aria-pressed={raw} onClick={() => setRaw((v) => !v)}>
          {raw ? 'Xem đã render' : 'Xem gốc'}
        </Button>
      </div>
      {raw ? (
        <pre className="overflow-x-auto rounded-lg border border-line bg-surface-2 p-4 text-sm whitespace-pre-wrap break-words">
          {text}
        </pre>
      ) : (
        <div className="md-body max-w-none break-words">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeSanitize]}
            components={{
              table: (p) => (
                <div className="my-3 overflow-x-auto">
                  <table>{p.children}</table>
                </div>
              ),
            }}
          >
            {text}
          </ReactMarkdown>
        </div>
      )}
    </div>
  )
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-muted">
      {children}
    </p>
  )
}
