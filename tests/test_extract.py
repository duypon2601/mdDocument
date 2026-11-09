"""parsers/extract: text, CSV, chuỗi dự phòng Docling -> MarkItDown -> HTML."""

import base64
import sys
import types

import pytest

from ingest.convert.parsers import extract as ex
from ingest.core.errors import FILE_CORRUPTED, IngestError
from ingest.core.markdown import Piece, split_markdown_tables

LONG = "Điều 3: Thanh toán trong vòng 30 ngày kể từ ngày ký."


# ---- hàm thuần ----


def test_piece_hash_stable():
    assert Piece("abc").content_hash == Piece("abc", "TABLE").content_hash
    assert Piece("abc").content_hash != Piece("abd").content_hash


def test_is_poor_extraction():
    assert ex.is_poor_extraction([])
    assert ex.is_poor_extraction([Piece("ngắn")])
    # ảnh không tính vào số ký tự dùng được
    assert ex.is_poor_extraction([Piece("x" * 500, "IMAGE")])
    assert not ex.is_poor_extraction([Piece(LONG)])
    assert not ex.is_poor_extraction([Piece("a" * 10), Piece("b" * 10, "TABLE")])


def test_pieces_to_markdown_skips_images():
    md = ex.pieces_to_markdown([Piece(" A "), Piece("base64...", "IMAGE"), Piece("| t |", "TABLE")])
    assert md == "A \n\n| t |"


def test_ext():
    assert ex._ext("Bao.Cao.DOCX") == ".docx"
    assert ex._ext("README") == ""


def test_split_markdown_tables():
    text = "Mở đầu\n\n| a | b |\n|---|---|\n| 1 | 2 |\nKết luận"
    pieces = split_markdown_tables(text)
    assert [(p.content_type, p.content) for p in pieces] == [
        ("TEXT", "Mở đầu"),
        ("TABLE", "| a | b |\n|---|---|\n| 1 | 2 |"),
        ("TEXT", "Kết luận"),
    ]


def test_split_markdown_tables_only_table():
    pieces = split_markdown_tables("| a |\n| 1 |")
    assert [p.content_type for p in pieces] == ["TABLE"]


def test_resolve_page():
    entry = types.SimpleNamespace
    assert ex._resolve_page(entry(prov=[entry(page_no=0), entry(page_no=3)])) == 3
    assert ex._resolve_page(entry(prov=[entry(page_no="2")])) is None
    assert ex._resolve_page(entry(prov=None)) is None
    assert ex._resolve_page(object()) is None


# ---- text / csv ----


def test_plain_text_utf8_bom():
    data = "﻿Xin chào\n".encode()
    assert ex.extract_bytes(data, "a.txt", "text") == "Xin chào"


def test_plain_text_empty():
    assert ex.extract_bytes(b"   \n", "a.md", "text") == ""


def test_csv_to_markdown_table_pads_and_trims_rows():
    data = "Tên,Tuổi\nAn,30,thừa\nBình\n".encode()
    md = ex.extract_bytes(data, "ds.CSV", "text")
    assert md.splitlines() == [
        "| Tên | Tuổi |",
        "| --- | --- |",
        "| An | 30 |",
        "| Bình |  |",
    ]


def test_csv_empty():
    assert ex.extract_bytes(b"", "a.csv", "text") == ""


# ---- MarkItDown thật ----


def test_docx_real(docx_bytes):
    md = ex.extract_bytes(docx_bytes, "hd.docx", "docx")
    assert "Hợp đồng mẫu" in md and "Thanh toán" in md


def test_html_real():
    html = f"<html><body><nav>menu</nav><h1>Tiêu đề</h1><p>{LONG}</p></body></html>"
    md = ex.extract_bytes(html.encode(), "a.html", "html")
    assert "Tiêu đề" in md and "Thanh toán" in md


def test_truncated_docx_raises(docx_bytes):
    with pytest.raises(IngestError) as e:
        ex.extract_bytes(docx_bytes[: len(docx_bytes) // 2], "x.docx", "docx")
    assert e.value.code == FILE_CORRUPTED


# ---- chuỗi dự phòng (giả lập extractor) ----


def test_markitdown_poor_html_falls_back_to_html_parser(monkeypatch):
    monkeypatch.setattr(ex, "_try_markitdown", lambda *a: ([Piece("x")], None))
    md = ex.extract_bytes(f"<p>{LONG}</p>".encode(), "a.html", "html")
    assert "Thanh toán" in md


def test_html_fallback_empty_then_error(monkeypatch):
    monkeypatch.setattr(ex, "_try_markitdown", lambda *a: ([], ValueError("hỏng")))
    with pytest.raises(IngestError):
        ex.extract_bytes(b"<script>x</script>", "a.html", "html")


def test_poor_result_returned_when_no_error(monkeypatch):
    monkeypatch.setattr(ex, "_try_markitdown", lambda *a: ([Piece("ít chữ")], None))
    assert ex.extract_bytes(b"...", "a.pptx", "pptx") == "ít chữ"


def test_markitdown_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, "markitdown", None)
    assert ex._try_markitdown(b"x", ".docx", "a.docx") == ([], None)


def test_markitdown_empty_text(monkeypatch):
    fake = types.ModuleType("markitdown")

    class MarkItDown:
        def convert_stream(self, stream, file_extension):
            return types.SimpleNamespace(text_content="  ")

    fake.MarkItDown = MarkItDown
    monkeypatch.setitem(sys.modules, "markitdown", fake)
    assert ex._try_markitdown(b"x", ".docx", "a.docx") == ([], None)


def test_prefer_docling_good_result_used(monkeypatch):
    monkeypatch.setattr(ex, "_try_docling", lambda *a: [Piece(LONG)])
    monkeypatch.setattr(ex, "_try_markitdown", lambda *a: pytest.fail("không được gọi"))
    assert ex.extract_bytes(b"x", "a.docx", "docx", prefer_docling=True) == LONG


def test_prefer_docling_poor_falls_back(monkeypatch):
    monkeypatch.setattr(ex, "_try_docling", lambda *a: [Piece("x")])
    monkeypatch.setattr(ex, "_try_markitdown", lambda *a: ([Piece(LONG)], None))
    assert ex.extract_bytes(b"x", "a.docx", "docx", prefer_docling=True) == LONG


# ---- _try_docling với module docling giả ----


class _Item:
    def __init__(self, page=1):
        self.prov = [types.SimpleNamespace(page_no=page)]


class TextItem(_Item):
    def __init__(self, text, page=1):
        super().__init__(page)
        self.text = text


class TableItem(_Item):
    def __init__(self, md, page=1):
        super().__init__(page)
        self.md = md

    def export_to_markdown(self, doc):
        if isinstance(self.md, Exception):
            raise self.md
        return self.md


class _Img:
    def save(self, buf, format):
        buf.write(b"PNG")


class PictureItem(_Item):
    def __init__(self, image, page=1):
        super().__init__(page)
        self.image = image

    def get_image(self, doc):
        if isinstance(self.image, Exception):
            raise self.image
        return self.image


def _install_docling(monkeypatch, items=None, convert_error=None):
    conv = types.ModuleType("docling.document_converter")
    seen = {}

    class DocumentConverter:
        def convert(self, path):
            if convert_error:
                raise convert_error
            with open(path, "rb") as f:
                seen["data"] = f.read()
            seen["path"] = path
            doc = types.SimpleNamespace(iterate_items=lambda: [(it, 0) for it in items])
            return types.SimpleNamespace(document=doc)

    conv.DocumentConverter = DocumentConverter
    doc_mod = types.ModuleType("docling_core.types.doc")
    doc_mod.PictureItem, doc_mod.TableItem, doc_mod.TextItem = PictureItem, TableItem, TextItem
    monkeypatch.setitem(sys.modules, "docling", types.ModuleType("docling"))
    monkeypatch.setitem(sys.modules, "docling.document_converter", conv)
    monkeypatch.setitem(sys.modules, "docling_core", types.ModuleType("docling_core"))
    monkeypatch.setitem(sys.modules, "docling_core.types", types.ModuleType("docling_core.types"))
    monkeypatch.setitem(sys.modules, "docling_core.types.doc", doc_mod)
    return seen


def test_docling_not_installed(monkeypatch):
    monkeypatch.setitem(sys.modules, "docling.document_converter", None)
    assert ex._try_docling(b"x", ".docx", "a.docx") == []


def test_docling_convert_error_returns_empty(monkeypatch):
    _install_docling(monkeypatch, convert_error=RuntimeError("boom"))
    assert ex._try_docling(b"x", ".docx", "a.docx") == []


def test_docling_items_to_pieces(monkeypatch):
    items = [
        TextItem("  Tiêu đề  ", page=1),
        TextItem("   "),  # rỗng: bỏ
        TableItem("| a |\n| 1 |", page=2),
        TableItem("| - |"),  # không có chữ/số: bỏ
        TableItem(RuntimeError("lỗi bảng")),  # lỗi: bỏ qua
        PictureItem(_Img(), page=3),
        PictureItem(None),  # không có ảnh: bỏ
        PictureItem(RuntimeError("lỗi ảnh")),  # lỗi: bỏ qua
        object(),  # loại khác: bỏ
    ]
    seen = _install_docling(monkeypatch, items)
    pieces = ex._try_docling(b"du lieu", ".docx", "a.docx")
    assert seen["data"] == b"du lieu" and seen["path"].endswith(".docx")
    assert [(p.content_type, p.page) for p in pieces] == [
        ("TEXT", "1"),
        ("TABLE", "2"),
        ("IMAGE", "3"),
    ]
    assert pieces[0].content == "Tiêu đề"

    assert base64.b64decode(pieces[2].content) == b"PNG"
    assert pieces[2].metadata == {"mime_type": "image/png"}


def test_docling_item_without_page(monkeypatch):
    item = TextItem("abc")
    item.prov = []
    _install_docling(monkeypatch, [item])
    assert ex._try_docling(b"x", ".docx", "a.docx")[0].page == ""
