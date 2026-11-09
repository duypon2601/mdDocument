"""Kiểm tra file upload: MIME thật (python-magic, rơi về chữ ký), dung lượng, định dạng."""

from dataclasses import dataclass
from pathlib import PurePosixPath

from ingest.core.errors import UNSUPPORTED_FORMAT

PDF = "application/pdf"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
HTML = "text/html"
TEXT = "text/plain"
MARKDOWN = "text/markdown"

IMAGE_MIMES = frozenset({"image/png", "image/jpeg", "image/tiff", "image/bmp", "image/webp"})
SUPPORTED_MIMES = frozenset({PDF, DOCX, PPTX, XLSX, HTML, TEXT, MARKDOWN}) | IMAGE_MIMES

EXT_MIME = {
    ".pdf": PDF, ".docx": DOCX, ".pptx": PPTX, ".xlsx": XLSX,
    ".html": HTML, ".htm": HTML, ".txt": TEXT, ".md": MARKDOWN, ".markdown": MARKDOWN,
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".tif": "image/tiff", ".tiff": "image/tiff", ".bmp": "image/bmp", ".webp": "image/webp",
}  # fmt: skip

_ZIP_MIMES = {"application/zip", "application/octet-stream", "application/x-zip-compressed"}
_TEXTUAL = {TEXT, MARKDOWN, HTML, "text/xml", "application/xml", "text/csv"}


class ValidationError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 415) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class ValidatedFile:
    file_name: str
    mime: str
    size: int


def safe_name(name: str | None) -> str:
    """Chỉ giữ tên file, bỏ đường dẫn."""
    base = PurePosixPath((name or "").replace("\\", "/")).name.strip()
    return base if base not in ("", ".", "..") else "unnamed"


def _sniff(data: bytes) -> str | None:
    """Nhận dạng theo chữ ký đầu file khi không có libmagic."""
    head = data[:2048]
    if head.startswith(b"%PDF-"):
        return PDF
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head[:4] in (b"II*\x00", b"MM\x00*"):
        return "image/tiff"
    if head.startswith(b"BM"):
        return "image/bmp"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith(b"PK\x03\x04"):
        return "application/zip"
    low = head.lstrip().lower()
    if low.startswith((b"<!doctype html", b"<html")) or b"<html" in low[:1024]:
        return HTML
    if b"\x00" not in head:
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as e:
            if e.start < len(head) - 4:  # lỗi giữa chừng, không phải cắt ngang ký tự
                return None
        return TEXT
    return None


def _magic(data: bytes) -> str | None:
    try:
        import magic

        return magic.from_buffer(data[:8192], mime=True)
    except Exception:  # thiếu libmagic hoặc lỗi nhận dạng
        return _sniff(data)


def _office_by_zip(data: bytes) -> str | None:
    import io
    import zipfile

    try:
        names = zipfile.ZipFile(io.BytesIO(data)).namelist()
    except zipfile.BadZipFile:
        return None
    if any(n.startswith("word/") for n in names):
        return DOCX
    if any(n.startswith("ppt/") for n in names):
        return PPTX
    if any(n.startswith("xl/") for n in names):
        return XLSX
    return None


def detect_mime(file_name: str, data: bytes) -> str:
    ext_mime = EXT_MIME.get(PurePosixPath(file_name).suffix.lower())
    real = _magic(data)
    if real in _ZIP_MIMES or (real or "").startswith("application/vnd.openxmlformats"):
        # Office là zip: ưu tiên nội dung zip, đuôi file chỉ để chốt khi nội dung không rõ
        return _office_by_zip(data) or (ext_mime if ext_mime in (DOCX, PPTX, XLSX) else real or "")
    if real in _TEXTUAL:
        # text/plain thật có thể là .md hoặc .html mà libmagic không phân biệt được
        if ext_mime in (MARKDOWN, HTML, TEXT):
            return ext_mime
        return real or ""
    return real or ""  # nội dung không nhận ra thì không tin đuôi file


def validate_upload(file_name: str, data: bytes, max_bytes: int) -> ValidatedFile:
    name = safe_name(file_name)
    if not data:
        raise ValidationError("EMPTY_FILE", "File rỗng", 400)
    if len(data) > max_bytes:
        raise ValidationError("FILE_TOO_LARGE", f"File vượt quá {max_bytes} byte", 413)
    mime = detect_mime(name, data)
    if mime not in SUPPORTED_MIMES:
        raise ValidationError(UNSUPPORTED_FORMAT, f"Định dạng không hỗ trợ: {mime or 'không rõ'}")
    return ValidatedFile(name, mime, len(data))
