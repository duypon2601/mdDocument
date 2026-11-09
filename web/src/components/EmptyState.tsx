import type { ReactNode } from 'react'

interface Props {
  title: string
  children?: ReactNode
  action?: ReactNode
}

export function EmptyState({ title, children, action }: Props) {
  return (
    <div className="rounded-lg border border-dashed border-line px-4 py-10 text-center">
      <p className="font-medium">{title}</p>
      {children && <p className="mt-1 text-sm text-muted">{children}</p>}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  )
}
