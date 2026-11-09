import { useRef, useState } from 'react'
import { ApiError } from '../../api/client'
import { useUpload } from '../../api/hooks'

type Item =
  | { id: number; name: string; state: 'sending' }
  | { id: number; name: string; state: 'accepted' }
  | { id: number; name: string; state: 'duplicate' }
  | { id: number; name: string; state: 'error'; detail: string }

const STATE_TEXT = {
  sending: 'Đang gửi…',
  accepted: 'Đã nhận',
  duplicate: 'Trùng, dùng lại kết quả',
  error: 'Lỗi',
} as const

export function UploadPanel() {
  const [items, setItems] = useState<Item[]>([])
  const [dragging, setDragging] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const nextId = useRef(1)
  const queue = useRef<Promise<void>>(Promise.resolve())
  const upload = useUpload()

  const patch = (id: number, next: Item) =>
    setItems((xs) => xs.map((x) => (x.id === id ? next : x)))

  function enqueue(files: File[]) {
    const added = files.map((f) => ({ id: nextId.current++, name: f.name }))
    setItems((xs) => [...added.map((a) => ({ ...a, state: 'sending' as const })), ...xs])
    // Gửi lần lượt từng file để không dồn nghẽn API
    files.forEach((file, i) => {
      const { id, name } = added[i]
      queue.current = queue.current.then(async () => {
        try {
          const r = await upload.mutateAsync({ file, profile: 'v2' })
          patch(id, { id, name, state: r.duplicate ? 'duplicate' : 'accepted' })
        } catch (e) {
          const detail = e instanceof ApiError ? e.detail : 'Không gửi được'
          patch(id, { id, name, state: 'error', detail })
        }
      })
    })
  }

  function pick(list: FileList | null) {
    const files = list ? Array.from(list) : []
    if (files.length) enqueue(files)
    if (inputRef.current) inputRef.current.value = ''
  }

  return (
    <section aria-labelledby="upload-title" className="mb-6 rounded-lg border border-line bg-surface p-4">
      <h2 id="upload-title" className="mb-3 text-lg font-semibold">
        Tải tài liệu lên
      </h2>

      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          pick(e.dataTransfer.files)
        }}
        className={`rounded-lg border-2 border-dashed px-4 py-8 text-center ${dragging ? 'border-accent bg-run-bg' : 'border-line'}`}
      >
        <p className="text-sm text-muted">Kéo thả file vào đây, hoặc</p>
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="mt-2 inline-flex min-h-9 items-center rounded-md bg-accent px-3.5 text-sm font-medium text-accent-fg hover:opacity-90"
        >
          Chọn file
        </button>
        <input
          ref={inputRef}
          type="file"
          multiple
          aria-label="Chọn file để tải lên"
          className="sr-only"
          tabIndex={-1}
          onChange={(e) => pick(e.target.files)}
        />
      </div>

      {items.length > 0 && (
        <ul aria-label="Tiến trình tải lên" className="mt-3 divide-y divide-line text-sm">
          {items.map((it) => (
            <li key={it.id} className="flex flex-wrap items-baseline justify-between gap-2 py-1.5">
              <span className="min-w-0 break-all">{it.name}</span>
              <span
                className={
                  it.state === 'error'
                    ? 'text-bad-fg'
                    : it.state === 'accepted'
                      ? 'text-ok-fg'
                      : 'text-muted'
                }
              >
                {STATE_TEXT[it.state]}
                {it.state === 'error' && `: ${it.detail}`}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
