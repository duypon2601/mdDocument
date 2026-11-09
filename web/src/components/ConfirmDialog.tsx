import { useEffect, useId, useRef, type ReactNode } from 'react'
import { Button, type ButtonVariant } from './Button'

interface Props {
  open: boolean
  title: string
  children?: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  variant?: ButtonVariant
  onConfirm: () => void
  onCancel: () => void
}

/** Hộp thoại xác nhận bằng <dialog>: trình duyệt lo bẫy focus và Esc. */
export function ConfirmDialog({
  open,
  title,
  children,
  confirmLabel = 'Xác nhận',
  cancelLabel = 'Quay lại',
  variant = 'danger',
  onConfirm,
  onCancel,
}: Props) {
  const ref = useRef<HTMLDialogElement>(null)
  const titleId = useId()

  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (open && !el.open) el.showModal()
    if (!open && el.open) el.close()
  }, [open])

  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      onCancel={(e) => {
        e.preventDefault() // để trạng thái open do component cha quyết định
        onCancel()
      }}
      className="m-auto w-[min(28rem,calc(100vw-2rem))] rounded-lg border border-line bg-surface p-5 text-fg shadow-xl"
    >
      <h2 id={titleId} className="text-lg font-semibold">
        {title}
      </h2>
      {children && <div className="mt-2 text-sm text-muted">{children}</div>}
      <div className="mt-5 flex justify-end gap-2">
        <Button onClick={onCancel}>{cancelLabel}</Button>
        <Button variant={variant} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  )
}
