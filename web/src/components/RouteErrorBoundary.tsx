import { Component, type ReactNode } from 'react'
import { ErrorState } from './ErrorState'

interface Props {
  children: ReactNode
  /** Đổi giá trị này (ví dụ pathname) thì boundary tự reset. */
  resetKey?: string
}

/** Bắt lỗi render và lỗi tải chunk lazy (ví dụ vừa deploy bản mới), cho phép tải lại trang. */
export class RouteErrorBoundary extends Component<Props, { error: Error | null; key?: string }> {
  state: { error: Error | null; key?: string } = { error: null, key: this.props.resetKey }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  static getDerivedStateFromProps(props: Props, state: { error: Error | null; key?: string }) {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <ErrorState
        title="Không hiển thị được trang này"
        detail={this.state.error.message}
        onRetry={() => window.location.reload()}
      />
    )
  }
}
