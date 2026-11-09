import { useEffect } from 'react'

const APP = 'Ingestion'

/** Đặt tiêu đề tab trình duyệt theo trang; để trống thì chỉ còn tên app. */
export function useDocumentTitle(title?: string) {
  useEffect(() => {
    document.title = title ? `${title} · ${APP}` : APP
  }, [title])
}
