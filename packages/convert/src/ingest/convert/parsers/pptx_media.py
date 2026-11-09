# Shape order adapted from MarkItDown PptxConverter (MIT, Copyright (c) Microsoft Corporation)
"""pptx thành Markdown, có ảnh và chart.

MarkItDown chỉ để lại `![tên](Picture1.jpg)` cho ảnh, nên ảnh trong slide không được
OCR. Module này duyệt slide theo đúng thứ tự của MarkItDown (sắp theo top rồi left,
đi vào group) và:

- Ảnh: đặt marker `<!-- image: ppt/media/imageN.png -->` đúng chỗ. "Slot" là một lần ảnh
  xuất hiện, giống docx_images, nên detect_format và ocr_pages ra cùng danh sách.
  finalize_markdown thay marker bằng nội dung OCR/Vision.
- Chart: đọc thẳng XML của chart (xlsx_media.chart_part_markdown) thành bảng, đủ loại
  chart mà MarkItDown báo "[unsupported chart]" (scatter, bubble...).
"""

from __future__ import annotations

import io
import logging
import posixpath
import zipfile

from ingest.convert.parsers import xlsx_media
from ingest.convert.parsers.docx_images import RASTER_EXT, image_marker

logger = logging.getLogger(__name__)


def _shape_key(shape):
    return (
        float("-inf") if shape.top is None else shape.top,
        float("-inf") if shape.left is None else shape.left,
    )


def _walk(shapes):
    """Shape theo thứ tự đọc của MarkItDown; group được duyệt sau chính nó."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    for shape in sorted(shapes, key=_shape_key):
        yield shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            yield from _walk(shape.shapes)


def _picture_part(shape) -> str | None:
    """Đường dẫn ảnh trong zip (ppt/media/...) nếu shape là ảnh."""
    rid = getattr(shape._element, "blip_rId", None)
    if not rid:
        return None
    try:
        return str(shape.part.related_part(rid).partname).lstrip("/")
    except (KeyError, AttributeError):
        return None


def _cell(v: str) -> str:
    return v.replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _table_markdown(table) -> str:
    rows = [[_cell(c.text or "") for c in row.cells] for row in table.rows]
    rows = [r for r in rows if any(r)]
    if not rows:
        return ""
    n = max(len(r) for r in rows)
    rows = [r + [""] * (n - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "| " + " | ".join("---" for _ in rows[0]) + " |"]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


def _open(data: bytes):
    from pptx import Presentation

    return Presentation(io.BytesIO(data))


def image_slots(data: bytes) -> list[str]:
    """Ảnh theo thứ tự xuất hiện trong các slide (một ảnh có thể lặp nhiều lần)."""
    slots: list[str] = []
    for slide in _open(data).slides:
        for shape in _walk(slide.shapes):
            name = _picture_part(shape)
            if name:
                slots.append(name)
    return slots


def readable_slot_indices(data: bytes, min_bytes: int) -> list[int]:
    """Slot cần đọc: lần xuất hiện đầu của mỗi ảnh raster đủ lớn."""
    slots = image_slots(data)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        sizes = {i.filename: i.file_size for i in z.infolist()}
    seen: set[str] = set()
    out: list[int] = []
    for idx, name in enumerate(slots):
        if name in seen:
            continue
        seen.add(name)
        ext = posixpath.splitext(name)[1].lower()
        if ext in RASTER_EXT and sizes.get(name, 0) >= min_bytes:
            out.append(idx)
    return out


def to_markdown(data: bytes) -> str:
    """Markdown của cả file, ảnh là marker, chart là bảng."""
    prs = _open(data)
    z = zipfile.ZipFile(io.BytesIO(data))
    out: list[str] = []
    chart_no = 0
    for slide_num, slide in enumerate(prs.slides, 1):
        out.append(f"<!-- Slide number: {slide_num} -->")
        title = slide.shapes.title
        for shape in _walk(slide.shapes):
            name = _picture_part(shape)
            if name:
                alt = shape._element.xpath("./*/p:cNvPr/@descr")
                if alt and alt[0].strip():
                    out.append(f"Ảnh: {' '.join(alt[0].split())}")
                out.append(image_marker(name))
            if getattr(shape, "has_table", False):
                md = _table_markdown(shape.table)
                if md:
                    out.append(md)
            if getattr(shape, "has_chart", False):
                chart_no += 1
                heading = f"Biểu đồ {chart_no} (slide {slide_num})"
                path = str(shape.chart.part.partname).lstrip("/")
                try:
                    md = xlsx_media.chart_part_markdown(z, path, heading)
                except Exception:
                    logger.warning("Chart %s lỗi; bỏ qua.", path, exc_info=True)
                    md = ""
                if md:
                    out.append(md)
            elif getattr(shape, "has_text_frame", False):
                text = (shape.text or "").strip()
                if text:
                    out.append(f"# {text}" if shape == title else text)
        if slide.has_notes_slide:
            frame = slide.notes_slide.notes_text_frame
            notes = (frame.text or "").strip() if frame is not None else ""
            if notes:
                out.append(f"### Ghi chú\n\n{notes}")
    return "\n\n".join(out).strip()
