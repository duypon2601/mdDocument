"""PDF: mở file, phân loại trang có/không có lớp text, chuyển trang sang Markdown."""

import re

import pymupdf

from ingest.convert.parsers.extract import Piece, is_poor_extraction
from ingest.core.errors import FILE_CORRUPTED, PASSWORD_PROTECTED, IngestError


def open_pdf(data: bytes) -> pymupdf.Document:
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as e:
        raise IngestError(FILE_CORRUPTED, f"Không mở được PDF: {e}") from e
    if doc.needs_pass:
        raise IngestError(PASSWORD_PROTECTED, "PDF có mật khẩu")
    if doc.page_count == 0:
        raise IngestError(FILE_CORRUPTED, "PDF không có trang nào")
    return doc


def classify_pages(doc: pymupdf.Document) -> tuple[list[int], list[int]]:
    """Trả (trang có text, trang cần OCR), chỉ số 0-based."""
    text_pages: list[int] = []
    ocr_pages: list[int] = []
    for i in range(doc.page_count):
        try:
            txt = doc[i].get_text("text").strip()
        except Exception as e:
            raise IngestError(FILE_CORRUPTED, f"Trang {i + 1} hỏng: {e}") from e
        poor = is_poor_extraction([Piece(txt)] if txt else [])  # trang ảnh thì cần OCR
        (ocr_pages if poor else text_pages).append(i)
    return text_pages, ocr_pages


def render_page_png(doc: pymupdf.Document, index: int, dpi: int = 200) -> bytes:
    return doc[index].get_pixmap(dpi=dpi).tobytes("png")


# ---------- ảnh trên trang có chữ ----------
#
# Trang vừa có chữ vừa có ảnh (chart, sơ đồ, bảng chụp) không đi OCR cả trang, nên ảnh
# bị bỏ qua; còn pymupdf4llm thì tự OCR ảnh và để lại khối "picture text" toàn chữ vụn.
# Ở đây mỗi ảnh đủ lớn là một "hình", đọc riêng bằng OCR/Vision LLM như ảnh docx,
# và nội dung được chèn vào đúng chỗ ảnh trong trang.
#
# Trong ocr_page_batches, số < page_count là trang OCR cả trang, số >= page_count là
# hình thứ (n - page_count) của list_figures. Danh sách chỉ phụ thuộc nội dung file.

MIN_FIGURE_PT = 72  # cạnh ngắn dưới 1 inch: logo, icon
MIN_FIGURE_PX = 64
MAX_FIGURE_PAGE_RATIO = 0.85  # ảnh phủ gần hết trang là nền/khung, không phải hình
FIGURE_DPI = 200


def list_figures(doc: pymupdf.Document, pages: list[int]) -> list[tuple[int, pymupdf.Rect]]:
    """[(trang 0-based, khung ảnh)] theo thứ tự trang, rồi từ trên xuống, trái sang phải."""
    out: list[tuple[int, pymupdf.Rect]] = []
    for i in pages:
        page = doc[i]
        page_area = page.rect.get_area() or 1.0
        boxes: list[pymupdf.Rect] = []
        try:
            infos = page.get_image_info()
        except Exception:
            continue
        for info in infos:
            r = pymupdf.Rect(info["bbox"]) & page.rect
            if r.is_empty or min(r.width, r.height) < MIN_FIGURE_PT:
                continue
            if min(info.get("width", 0), info.get("height", 0)) < MIN_FIGURE_PX:
                continue
            if r.get_area() > MAX_FIGURE_PAGE_RATIO * page_area:
                continue
            if any(_cover(r, b) > 0.9 and _cover(b, r) > 0.9 for b in boxes):
                continue  # cùng ảnh vẽ hai lần
            boxes.append(r)
        boxes.sort(key=lambda r: (round(r.y0), round(r.x0)))
        out += [(i, r) for r in boxes]
    return out


def _cover(a: pymupdf.Rect, b: pymupdf.Rect) -> float:
    """Phần diện tích của a nằm trong b."""
    area = a.get_area()
    return (a & b).get_area() / area if area else 0.0


def figure_name(n: int) -> str:
    return f"pdf-figure-{n + 1}"


def render_figure_png(doc: pymupdf.Document, page: int, bbox, dpi: int = FIGURE_DPI) -> bytes:
    return doc[page].get_pixmap(dpi=dpi, clip=pymupdf.Rect(bbox)).tobytes("png")


def _clean_picture_text(text: str) -> str:
    """Chữ thật nằm trong vùng hình (chart vẽ bằng vector): bỏ marker, <br> thành xuống dòng."""
    text = text.replace("<!-- Start of picture text -->", "").replace(
        "<!-- End of picture text -->", ""
    )
    lines = [ln.strip() for ln in text.replace("<br>", "\n").splitlines()]
    return "\n".join(ln for ln in lines if ln)


def page_markdown_with_figures(
    doc: pymupdf.Document, index: int, figures: list[tuple[str, pymupdf.Rect]]
) -> str:
    """Markdown của trang có chữ, mỗi hình thay bằng marker `<!-- image: tên -->`.

    Không để pymupdf4llm OCR (use_ocr=False): hình đã có đường OCR/Vision riêng. Hình
    không khớp khối "picture" nào của layout thì marker nằm cuối trang.
    """
    import pymupdf4llm

    from ingest.convert.parsers.docx_images import image_marker

    try:
        chunk = pymupdf4llm.to_markdown(
            doc, pages=[index], show_progress=False, page_chunks=True, use_ocr=False
        )[0]
        text, boxes = chunk.get("text", ""), chunk.get("page_boxes") or []
    except Exception:
        text, boxes = doc[index].get_text("text"), []

    out: list[str] = []
    pos = 0
    used: set[str] = set()
    pictures = sorted((b for b in boxes if b.get("class") == "picture"), key=lambda b: b["pos"])
    for box in pictures:
        start, end = box["pos"]
        if start < pos:
            continue
        out.append(text[pos:start])
        pos = end
        rect = pymupdf.Rect(box["bbox"])
        match = next(
            (name for name, r in figures if name not in used and _cover(r, rect) > 0.5), None
        )
        if match:
            used.add(match)
            out.append(f"\n\n{image_marker(match)}\n\n")
        else:
            out.append(f"\n\n{_clean_picture_text(text[start:end])}\n\n")
    out.append(text[pos:])
    out += [f"\n\n{image_marker(name)}" for name, _ in figures if name not in used]
    md = "\n".join(ln.rstrip() for ln in "".join(out).splitlines())
    return re.sub(r"\n{3,}", "\n\n", md).strip()
