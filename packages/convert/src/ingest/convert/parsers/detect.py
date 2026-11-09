"""Nhận dạng loại file từ nội dung (magic bytes), phần đuôi file chỉ là gợi ý phụ."""

import io
import zipfile
from pathlib import PurePath

from ingest.core.errors import FILE_CORRUPTED, PASSWORD_PROTECTED, UNSUPPORTED_FORMAT, IngestError

MIME = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "html": "text/html",
    "image": "image/*",
    "text": "text/plain",
}
TEXT_EXT = {".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".log"}
HTML_EXT = {".html", ".htm", ".xhtml"}
OFFICE_EXT = {".docx": "docx", ".pptx": "pptx", ".xlsx": "xlsx"}
IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"II*\x00", b"MM\x00*", b"BM", b"GIF8")
OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def sniff(data: bytes, file_name: str) -> tuple[str, str]:
    """Trả (kind, mime). Raise IngestError nếu không hỗ trợ hoặc file hỏng."""
    if not data:
        raise IngestError(FILE_CORRUPTED, "File rỗng")
    ext = PurePath(file_name).suffix.lower()
    if data.startswith(b"%PDF"):
        return "pdf", MIME["pdf"]
    if data.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile as e:
            raise IngestError(FILE_CORRUPTED, "File zip/office hỏng") from e
        for prefix, kind in (("word/", "docx"), ("ppt/", "pptx"), ("xl/", "xlsx")):
            if any(n.startswith(prefix) for n in names):
                return kind, MIME[kind]
        raise IngestError(UNSUPPORTED_FORMAT, "File zip không phải docx/pptx/xlsx")
    if data.startswith(OLE_MAGIC):
        if ext in OFFICE_EXT:  # OOXML có mật khẩu được bọc trong container OLE
            raise IngestError(PASSWORD_PROTECTED, "File office có mật khẩu")
        raise IngestError(UNSUPPORTED_FORMAT, "Định dạng Office cũ (.doc/.xls/.ppt)")
    if data.startswith(IMAGE_MAGIC):
        return "image", MIME["image"]
    if ext in OFFICE_EXT:
        raise IngestError(FILE_CORRUPTED, f"Đuôi {ext} nhưng nội dung không phải file Office")
    if ext == ".pdf":
        raise IngestError(FILE_CORRUPTED, "Đuôi .pdf nhưng không có header PDF")
    head = data[:2048].lstrip().lower()
    if ext in HTML_EXT or head.startswith((b"<!doctype html", b"<html")):
        return "html", MIME["html"]
    if b"\x00" not in data[:4096] and ext in TEXT_EXT:
        return "text", MIME["text"]
    raise IngestError(UNSUPPORTED_FORMAT, f"Không hỗ trợ định dạng {ext or '(không đuôi)'}")
