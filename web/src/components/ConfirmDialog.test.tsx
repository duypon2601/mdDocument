import { fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ConfirmDialog } from './ConfirmDialog'

function setup(open = true) {
  const onConfirm = vi.fn()
  const onCancel = vi.fn()
  render(
    <ConfirmDialog
      open={open}
      title="Dừng tài liệu?"
      confirmLabel="Dừng"
      onConfirm={onConfirm}
      onCancel={onCancel}
    >
      Workflow sẽ bị huỷ.
    </ConfirmDialog>,
  )
  return { onConfirm, onCancel }
}

describe('ConfirmDialog', () => {
  it('mở khi open=true và hiện tiêu đề, nội dung', () => {
    setup()
    expect(screen.getByRole('dialog', { name: 'Dừng tài liệu?' })).toBeInTheDocument()
    expect(screen.getByText('Workflow sẽ bị huỷ.')).toBeInTheDocument()
  })

  it('đóng khi open=false', () => {
    setup(false)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('bấm xác nhận gọi onConfirm', async () => {
    const { onConfirm, onCancel } = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Dừng' }))
    expect(onConfirm).toHaveBeenCalledOnce()
    expect(onCancel).not.toHaveBeenCalled()
  })

  it('bấm Quay lại gọi onCancel', async () => {
    const { onConfirm, onCancel } = setup()
    await userEvent.click(screen.getByRole('button', { name: 'Quay lại' }))
    expect(onCancel).toHaveBeenCalledOnce()
    expect(onConfirm).not.toHaveBeenCalled()
  })

  it('Esc (sự kiện cancel của dialog) gọi onCancel', () => {
    const { onCancel } = setup()
    fireEvent(screen.getByRole('dialog'), new Event('cancel', { cancelable: true }))
    expect(onCancel).toHaveBeenCalledOnce()
  })
})
