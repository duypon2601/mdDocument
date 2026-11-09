# Adapted from rag-starter (MIT, Copyright (c) 2026 Anas Ahmad)
"""Trích nội dung file không phải PDF thành Piece rồi sang Markdown.

Chuỗi dự phòng giữ nguyên ý của rag-starter:
    Docling (extra tùy chọn) -> MarkItDown -> parser riêng (html/plain text)
Bỏ phần pypdf, URL, sitemap, Confluence và Django diagnostics. PDF đi đường PyMuPDF
theo từng trang (xem parsers/pdf.py) vì cần biết trang nào phải OCR.
"""

from __future__ import annotations

import base64
import csv
import io
import logging

from ingest.convert.parsers import html as html_parser
from ingest.core.errors import FILE_CORRUPTED, IngestError
from ingest.core.markdown import Piece, split_markdown_tables

logger = logging.getLogger(__name__)

# Dưới ngưỡng này (ký tự TEXT + TABLE) coi như trích xuất kém, thử extractor kế tiếp
MIN_USABLE_CHARS = 20


def is_poor_extraction(pieces: list[Piece], min_chars: int = MIN_USABLE_CHARS) -> bool:
    """True khi kết quả có quá ít text/bảng dùng được."""
    usable = sum(len(p.content) for p in pieces if p.content_type in {"TEXT", "TABLE"})
    return not pieces or usable < min_chars


def pieces_to_markdown(pieces: list[Piece]) -> str:
    """Ảnh base64 không đưa vào Markdown; text và bảng nối theo thứ tự."""
    return "\n\n".join(p.content for p in pieces if p.content_type != "IMAGE").strip()


def extract_bytes(data: bytes, file_name: str, kind: str, prefer_docling: bool = False) -> str:
    """Trả Markdown cho docx/pptx/xlsx/html/text. Raise IngestError(FILE_CORRUPTED) nếu hỏng."""
    ext = f".{kind}" if kind in {"docx", "pptx", "xlsx", "html"} else _ext(file_name)
    if kind == "text":
        if ext == ".csv":
            pieces = _extract_csv(data)
        else:
            pieces = _extract_plain_text(data)
        return pieces_to_markdown(pieces)

    if prefer_docling:
        pieces = _try_docling(data, ext, file_name)
        if pieces and not is_poor_extraction(pieces):
            return pieces_to_markdown(pieces)

    pieces, markitdown_error = _try_markitdown(data, ext, file_name)
    if pieces and not is_poor_extraction(pieces):
        return pieces_to_markdown(pieces)

    if kind == "html":
        text = html_parser.html_to_markdown(data)
        if text:
            return text
    if markitdown_error is not None:
        raise IngestError(FILE_CORRUPTED, f"Không đọc được file {ext}: {markitdown_error}")
    return pieces_to_markdown(pieces)


def _ext(name: str) -> str:
    return "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _try_docling(data: bytes, ext: str, name: str) -> list[Piece]:
    """Docling: giữ cấu trúc bảng, trang. Cần extra `docling`."""
    import tempfile

    try:
        from docling.document_converter import DocumentConverter
        from docling_core.types.doc import PictureItem, TableItem, TextItem
    except ImportError:
        logger.debug("Docling chưa cài; bỏ qua. Cài: uv sync --extra docling")
        return []
    try:
        with tempfile.NamedTemporaryFile(suffix=ext) as tmp:
            tmp.write(data)
            tmp.flush()
            result = DocumentConverter().convert(tmp.name)
    except Exception:
        logger.warning("Docling lỗi trên '%s'; chuyển sang MarkItDown.", name, exc_info=True)
        return []

    pieces: list[Piece] = []
    for item, _level in result.document.iterate_items():
        page_no = _resolve_page(item)
        page = str(page_no) if page_no is not None else ""
        if isinstance(item, TableItem):
            try:
                md = item.export_to_markdown(doc=result.document)
            except Exception:
                continue
            if any(c.isalnum() for c in md):
                pieces.append(Piece(content=md, content_type="TABLE", page=page))
        elif isinstance(item, PictureItem):
            try:
                image = item.get_image(result.document)
                if image is None:
                    continue
                buf = io.BytesIO()
                image.save(buf, format="PNG")
                b64 = base64.b64encode(buf.getvalue()).decode()
                pieces.append(Piece(b64, "IMAGE", page, {"mime_type": "image/png"}))
            except Exception:
                logger.debug("Không lấy được ảnh trang %s.", page, exc_info=True)
        elif isinstance(item, TextItem):
            text = (item.text or "").strip()
            if text:
                pieces.append(Piece(content=text, content_type="TEXT", page=page))
    return pieces


def _resolve_page(item) -> int | None:
    """Lấy số trang dương từ provenance của Docling."""
    provenance = getattr(item, "prov", None)
    if isinstance(provenance, list):
        for entry in provenance:
            page = getattr(entry, "page_no", None)
            if isinstance(page, int) and page > 0:
                return page
    return None


def _try_markitdown(data: bytes, ext: str, name: str) -> tuple[list[Piece], Exception | None]:
    """MarkItDown xử lý Office/HTML mà không cần torch. Trả (pieces, lỗi nếu có)."""
    try:
        from markitdown import MarkItDown
    except ImportError:
        return [], None
    try:
        result = MarkItDown().convert_stream(io.BytesIO(data), file_extension=ext)
    except Exception as e:
        logger.warning("MarkItDown lỗi trên '%s'.", name, exc_info=True)
        return [], e
    text = (getattr(result, "text_content", "") or "").strip()
    return (split_markdown_tables(text) if text else []), None


def _extract_plain_text(data: bytes) -> list[Piece]:
    text = html_parser.decode_text(data).strip()
    return [Piece(content=text, content_type="TEXT")] if text else []


def _extract_csv(data: bytes) -> list[Piece]:
    """CSV thành bảng Markdown để LLM đọc được."""
    text = html_parser.decode_text(data)
    rows = list(csv.reader(io.StringIO(text, newline="")))
    if not rows:
        return []
    out = io.StringIO()
    header, *body = rows
    out.write("| " + " | ".join(header) + " |\n")
    out.write("| " + " | ".join("---" for _ in header) + " |\n")
    for row in body:
        padded = row + [""] * (len(header) - len(row))
        out.write("| " + " | ".join(padded[: len(header)]) + " |\n")
    return [Piece(content=out.getvalue().strip(), content_type="TABLE")]
