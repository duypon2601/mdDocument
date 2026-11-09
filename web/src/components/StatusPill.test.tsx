import { render, screen } from '@testing-library/react'
import { STATUSES } from '../api/types'
import { STATUS_LABEL } from '../lib/status'
import { StatusPill } from './StatusPill'

describe('StatusPill', () => {
  it.each(STATUSES)('%s hiện nhãn tiếng Việt', (s) => {
    render(<StatusPill status={s} />)
    expect(screen.getByText(STATUS_LABEL[s])).toBeInTheDocument()
  })

  it('tô màu theo nhóm', () => {
    const { rerender } = render(<StatusPill status="INDEXED" />)
    expect(screen.getByText('Hoàn tất')).toHaveAttribute('data-group', 'ok')
    rerender(<StatusPill status="FAILED" />)
    expect(screen.getByText('Lỗi')).toHaveAttribute('data-group', 'bad')
    rerender(<StatusPill status="INDEXING" />)
    expect(screen.getByText('Đang index')).toHaveAttribute('data-group', 'running')
  })
})
