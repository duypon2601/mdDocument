"""Chart gốc trong docx (word/charts/chartN.xml), phần MarkItDown (mammoth) bỏ qua.

Trước khi đưa file cho MarkItDown, mỗi `<w:drawing>` chứa chart được thay bằng một token
chữ. Mammoth giữ token đúng chỗ trong đoạn văn, sau đó token được thay bằng bảng dữ liệu
của chart (đọc bằng xlsx_media.chart_part_markdown). Token bị mất (Docling, chart trong
text box lạ...) thì bảng nối cuối tài liệu.

Chỉ đọc chart kiểu cũ (`c:chart`). Chart kiểu mới của Office 2016 (`cx:chart`: waterfall,
treemap...) có cấu trúc khác, chưa hỗ trợ.
"""

from __future__ import annotations

import io
import logging
import re
import zipfile

from ingest.convert.parsers import xlsx_media

logger = logging.getLogger(__name__)

DOC_PART = "word/document.xml"
TOKEN_RE = re.compile(r"QXCHART(\d{4})QX")
_DRAWING_RE = re.compile(rb"<w:drawing\b.*?</w:drawing>", re.S)
_CHART_RID_RE = re.compile(rb"<c:chart\b[^>]*?\br:id=\"([^\"]+)\"")


def _token(i: int) -> str:
    return f"QXCHART{i:04d}QX"


def tokenize_charts(data: bytes) -> tuple[bytes, list[str]]:
    """Trả (docx đã thay chart bằng token, [markdown từng chart]). Không có chart trả (data, [])."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        doc_xml = z.read(DOC_PART)
    except (zipfile.BadZipFile, KeyError):
        return data, []
    if b"<c:chart" not in doc_xml:
        return data, []
    rels = xlsx_media._rels(z, DOC_PART)
    charts: list[str] = []

    def sub(m: re.Match) -> bytes:
        rid = _CHART_RID_RE.search(m.group(0))
        target = rels.get(rid.group(1).decode()) if rid else None
        if target is None:
            return m.group(0)
        heading = f"Biểu đồ {len(charts) + 1}"
        try:
            md = xlsx_media.chart_part_markdown(z, target[0], heading)
        except Exception:
            logger.warning("Chart %s lỗi; bỏ qua.", target[0], exc_info=True)
            md = ""
        charts.append(md)
        token = _token(len(charts) - 1).encode()
        return b'<w:t xml:space="preserve"> ' + token + b" </w:t>"

    new_xml = _DRAWING_RE.sub(sub, doc_xml)
    if not charts:
        return data, []
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as w:
        for info in z.infolist():
            w.writestr(info, new_xml if info.filename == DOC_PART else z.read(info))
    return out.getvalue(), charts


def fill_tokens(md: str, charts: list[str]) -> str:
    """Thay token bằng bảng chart; chart không còn token thì nối cuối."""
    used: set[int] = set()

    def sub(m: re.Match) -> str:
        i = int(m.group(1))
        if i >= len(charts) or i in used:
            return ""
        used.add(i)
        return f"\n\n{charts[i]}\n\n" if charts[i] else ""

    out = TOKEN_RE.sub(sub, md)
    rest = [c for i, c in enumerate(charts) if i not in used and c]
    if rest:
        out = "\n\n".join([out.rstrip(), *rest])
    return re.sub(r"\n{3,}", "\n\n", out).strip()
