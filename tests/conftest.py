import io

import pymupdf
import pytest


def make_pdf(pages: list[str | None]) -> bytes:
    """str = trang có text, None = trang chỉ có ảnh (không có lớp text)."""
    doc = pymupdf.open()
    for txt in pages:
        page = doc.new_page()
        if txt is not None:
            page.insert_text((72, 100), txt, fontsize=12)
        else:
            pm = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
            pm.set_rect(pm.irect, (200, 200, 200))
            page.insert_image(pymupdf.Rect(72, 72, 272, 172), pixmap=pm)
    return doc.tobytes()


def make_docx() -> bytes:
    import docx

    d = docx.Document()
    d.add_heading("Hợp đồng mẫu", level=1)
    d.add_paragraph("Điều 3: Thanh toán trong vòng 30 ngày.")
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


@pytest.fixture
def pdf_bytes():
    return make_pdf


@pytest.fixture
def docx_bytes():
    return make_docx()
