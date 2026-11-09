"""Ảnh nhúng trong docx: tìm theo thứ tự xuất hiện, đọc ra PNG, chèn nội dung về đúng chỗ.

"Slot" là một lần ảnh xuất hiện trong word/document.xml (cùng một file ảnh có thể
xuất hiện nhiều lần). Chỉ số slot chỉ phụ thuộc nội dung file, nên detect_format và
ocr_pages tính ra cùng một danh sách dù chạy trên worker khác nhau.
"""

from __future__ import annotations

import io
import posixpath
import re
import zipfile
from xml.etree import ElementTree as ET

R_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
RASTER_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff"}  # emf/wmf/svg bỏ qua
MIN_SIDE_PX = 32

# MarkItDown (mammoth) để lại ![alt](data:image/png;base64...) đúng vị trí ảnh
PLACEHOLDER_RE = re.compile(r"!\[[^\]]*\]\(data:image/[^)]*\)")
MARKER_RE = re.compile(r"<!--\s*image:\s*(\S+?)\s*-->")


def image_marker(name: str) -> str:
    return f"<!-- image: {name} -->"


def has_media(data: bytes) -> bool:
    """Fast-path: docx không có thư mục word/media/ thì không có ảnh để đọc."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        return any(n.startswith("word/media/") for n in z.namelist())


def image_slots(data: bytes) -> list[str]:
    """Đường dẫn ảnh trong zip, theo thứ tự xuất hiện trong thân văn bản."""
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        try:
            rels_xml = z.read("word/_rels/document.xml.rels")
            doc_xml = z.read("word/document.xml")
        except KeyError:
            return []
    try:
        rels_root = ET.fromstring(rels_xml)
        doc_root = ET.fromstring(doc_xml)
    except ET.ParseError:
        return []
    rels: dict[str, str] = {}
    for rel in rels_root:
        target = rel.get("Target", "")
        if rel.get("TargetMode") == "External" or not target:
            continue
        path = target.lstrip("/") if target.startswith("/") else posixpath.join("word", target)
        rels[rel.get("Id", "")] = posixpath.normpath(path)
    slots: list[str] = []
    for el in doc_root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "blip":  # DrawingML
            rid = el.get(f"{R_NS}embed")
        elif tag == "imagedata":  # VML (file Word cũ lưu lại thành docx)
            rid = el.get(f"{R_NS}id")
        else:
            continue
        if rid and rels.get(rid) in names:
            slots.append(rels[rid])
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


def read_png(data: bytes, name: str) -> bytes | None:
    """Đọc ảnh trong zip, chuẩn hoá về PNG RGB. None nếu ảnh quá nhỏ để có chữ."""
    import pymupdf

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        raw = z.read(name)
    pix = pymupdf.Pixmap(raw)
    if min(pix.width, pix.height) < MIN_SIDE_PX:
        return None
    if pix.colorspace is not None and pix.colorspace.n not in (1, 3):  # CMYK...
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    if pix.alpha:
        pix = pymupdf.Pixmap(pix, 0)
    return pix.tobytes("png")


def mark_placeholders(md: str, slots: list[str]) -> str:
    """Đổi placeholder ảnh của MarkItDown thành marker theo slot.

    Số placeholder lệch số slot (ảnh trong text box, Docling...) thì không đoán vị trí:
    xoá hết placeholder, nội dung ảnh sẽ được nối cuối tài liệu.
    """
    found = PLACEHOLDER_RE.findall(md)
    if len(found) != len(slots):
        return PLACEHOLDER_RE.sub("", md)
    it = iter(slots)
    return PLACEHOLDER_RE.sub(lambda _m: image_marker(next(it)), md)


def split_image_blocks(part: str) -> tuple[str, dict[str, str]]:
    """Tách phần OCR ảnh docx thành (phần còn lại, {tên ảnh: nội dung})."""
    pieces = MARKER_RE.split(part)
    images: dict[str, str] = {}
    for i in range(1, len(pieces), 2):
        images[pieces[i]] = pieces[i + 1].strip()
    return pieces[0], images


def place_images(md: str, images: dict[str, str]) -> str:
    """Thay marker bằng nội dung ảnh (chỉ ở lần xuất hiện đầu); ảnh chưa có chỗ thì nối cuối."""
    used: set[str] = set()

    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name in used:
            return ""
        used.add(name)
        return images.get(name, "")

    out = MARKER_RE.sub(sub, md)
    rest = [t for name, t in images.items() if name not in used and t]
    if rest:
        out = "\n\n".join([out.rstrip(), *rest])
    return re.sub(r"\n{3,}", "\n\n", out).strip()
