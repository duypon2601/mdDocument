import { Button } from './Button'

interface Props {
  title?: string
  detail?: string
  onRetry?: () => void
}

export function ErrorState({ title = 'Có lỗi xảy ra', detail, onRetry }: Props) {
  return (
    <div role="alert" className="rounded-lg border border-bad-fg/40 bg-bad-bg px-4 py-6 text-bad-fg">
      <p className="font-medium">{title}</p>
      {detail && <p className="mt-1 text-sm break-words">{detail}</p>}
      {onRetry && (
        <Button className="mt-3" onClick={onRetry}>
          Thử lại
        </Button>
      )}
    </div>
  )
}
